// Claude x SolidWorks - thin, optional add-in (stage 1 skeleton).
//
// What it does, and nothing more:
//   1. a "Claude" command (Tools menu, toolbar, and a "Claude" tab in the CommandManager) that starts the
//      existing Python tab watcher (swpanel_taskpane.py watch) if it is not running yet
//   2. on SolidWorks start: writes a heartbeat file (connected.json) so test_registration.py can prove it loaded,
//      and starts the watcher too (the same mutex keeps it to one instance)
//   3. selection / active-document events: bumps a counter in ~/.solidworks-api/swpanel/events/sel.json so the
//      Python tab can react at once instead of polling every 2 s (the Python side does not read it yet)
//
// All the logic stays in the Python process. Nothing here touches the model; every handler is wrapped so an
// exception is logged, never thrown into SolidWorks.
//
// Built by build.ps1 with the csc.exe that ships with Windows (.NET Framework 4.x, C# 5): no Visual Studio needed.
// Keep it C# 5: no $"..." strings, no ?. , no nameof, no expression-bodied members.

using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swpublished;

[assembly: AssemblyTitle("Claude for SolidWorks add-in")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: ComVisible(false)]

namespace ClaudeSw
{
    [ComVisible(true)]
    [Guid("ddc81893-703c-404d-bffd-74d6781c5148")]
    [ProgId("ClaudeSw.Addin")]
    [ClassInterface(ClassInterfaceType.AutoDispatch)]   // CommandManager calls OpenPanel / OpenPanelEnable by name
    public class Addin : ISwAddin
    {
        const int GroupId = 27001;
        const int ItemOpen = 0;
        const string TabName = "Claude";
        const string WatchMutex = "Local\\swpanel_watch";   // the same name swpanel_taskpane.py watch() holds

        static readonly string Home = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".solidworks-api");
        static readonly string AddinDir = Path.Combine(Home, "addin");
        static readonly string EventsDir = Path.Combine(Path.Combine(Home, "swpanel"), "events");

        SldWorks sw;
        int cookie;
        ICommandManager cmdMgr;
        object hookedDoc;            // PartDoc / AssemblyDoc / DrawingDoc whose selection event we listen to
        long selSeq;

        // ---------------------------------------------------------------- ISwAddin
        public bool ConnectToSW(object ThisSW, int Cookie)
        {
            try
            {
                sw = (SldWorks)ThisSW;
                cookie = Cookie;
                sw.SetAddinCallbackInfo2(0, this, cookie);
                Directory.CreateDirectory(AddinDir);
                Heartbeat();
                Safe("commands", AddCommands);
                Safe("events", HookApp);
                Safe("autostart", StartWatcher);
            }
            catch (Exception e)
            {
                Log("connect failed: " + e);
            }
            return true;                 // never block SolidWorks from starting
        }

        public bool DisconnectFromSW()
        {
            Safe("unhook doc", UnhookDoc);
            Safe("unhook app", delegate { sw.ActiveModelDocChangeNotify -= OnActiveDocChange; });
            Safe("remove commands", RemoveCommands);
            if (cmdMgr != null) Marshal.ReleaseComObject(cmdMgr);
            cmdMgr = null;
            sw = null;
            GC.Collect();
            GC.WaitForPendingFinalizers();
            Log("disconnected");
            return true;
        }

        // ---------------------------------------------------------------- commands
        void AddCommands()
        {
            cmdMgr = sw.GetCommandManager(cookie);
            int err = 0;
            CommandGroup grp = cmdMgr.CreateCommandGroup2(GroupId, "Claude", "Claude for SolidWorks",
                "Open the Claude tab", -1, true, ref err);
            string[] icons = Icons();
            if (icons != null)
            {
                grp.IconList = icons;
                grp.MainIconList = icons;
            }
            grp.AddCommandItem2("Claude tab", -1, "Open the Claude chat tab in the Task Pane", "Claude tab", 0,
                "OpenPanel", "OpenPanelEnable", ItemOpen,
                (int)(swCommandItemType_e.swMenuItem | swCommandItemType_e.swToolbarItem));
            grp.HasToolbar = true;
            grp.HasMenu = true;
            grp.Activate();

            int id = grp.get_CommandID(ItemOpen);
            int[] docTypes = { (int)swDocumentTypes_e.swDocPART, (int)swDocumentTypes_e.swDocASSEMBLY,
                               (int)swDocumentTypes_e.swDocDRAWING };
            foreach (int t in docTypes)
            {
                CommandTab old = cmdMgr.GetCommandTab(t, TabName);
                if (old != null) cmdMgr.RemoveCommandTab(old);   // a tab left over from the last session
                CommandTab tab = cmdMgr.AddCommandTab(t, TabName);
                if (tab == null) continue;
                CommandTabBox box = tab.AddCommandTabBox();
                box.AddCommands(new int[] { id },
                    new int[] { (int)swCommandTabButtonTextDisplay_e.swCommandTabButton_TextBelow });
            }
            Log("commands added, err=" + err);
        }

        void RemoveCommands()
        {
            if (cmdMgr == null) return;
            int[] docTypes = { (int)swDocumentTypes_e.swDocPART, (int)swDocumentTypes_e.swDocASSEMBLY,
                               (int)swDocumentTypes_e.swDocDRAWING };
            foreach (int t in docTypes)
            {
                CommandTab tab = cmdMgr.GetCommandTab(t, TabName);
                if (tab != null) cmdMgr.RemoveCommandTab(tab);
            }
            cmdMgr.RemoveCommandGroup(GroupId);
        }

        // CommandManager callbacks (public, found by name through IDispatch)
        public void OpenPanel()
        {
            Safe("open panel", delegate
            {
                if (WatcherRunning())
                {
                    Log("open panel: watcher already running");
                    sw.SendMsgToUser2("The Claude tab is already running: look for it in the Task Pane.",
                        (int)swMessageBoxIcon_e.swMbInformation, (int)swMessageBoxBtn_e.swMbOk);
                    return;
                }
                StartWatcher();
                sw.SendMsgToUser2("Starting the Claude tab: it appears in the Task Pane in about 10 seconds.",
                    (int)swMessageBoxIcon_e.swMbInformation, (int)swMessageBoxBtn_e.swMbOk);
            });
        }

        public int OpenPanelEnable()
        {
            return 1;
        }

        // ---------------------------------------------------------------- the Python tab
        static bool WatcherRunning()
        {
            Mutex m;
            if (Mutex.TryOpenExisting(WatchMutex, out m))
            {
                m.Dispose();
                return true;
            }
            return false;
        }

        void StartWatcher()
        {
            if (WatcherRunning()) return;
            string pythonw = Config("pythonw");
            string script = Config("script");
            if (string.IsNullOrEmpty(pythonw) || !File.Exists(pythonw) || string.IsNullOrEmpty(script) ||
                !File.Exists(script))
            {
                Log("watcher not started: config.txt has no valid pythonw / script (re-run register.ps1)");
                return;
            }
            ProcessStartInfo psi = new ProcessStartInfo(pythonw, "\"" + script + "\" watch");
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WorkingDirectory = Path.GetDirectoryName(script);
            Process.Start(psi);
            Log("watcher started: " + pythonw + " " + script);
        }

        // ~/.solidworks-api/addin/config.txt, written by register.ps1: one key=value per line
        static string Config(string key)
        {
            string path = Path.Combine(AddinDir, "config.txt");
            if (!File.Exists(path)) return null;
            foreach (string line in File.ReadAllLines(path, Encoding.UTF8))
            {
                int i = line.IndexOf('=');
                if (i > 0 && line.Substring(0, i).Trim() == key) return line.Substring(i + 1).Trim();
            }
            return null;
        }

        // ---------------------------------------------------------------- events
        void HookApp()
        {
            sw.ActiveModelDocChangeNotify += OnActiveDocChange;
            HookDoc(sw.ActiveDoc);
        }

        int OnActiveDocChange()
        {
            Safe("doc change", delegate
            {
                UnhookDoc();
                HookDoc(sw.ActiveDoc);
                Bump("doc");
            });
            return 0;
        }

        void HookDoc(object doc)
        {
            if (doc == null) return;
            PartDoc part = doc as PartDoc;
            AssemblyDoc asm = doc as AssemblyDoc;
            DrawingDoc drw = doc as DrawingDoc;
            if (part != null) part.UserSelectionPostNotify += OnSelection;
            else if (asm != null) asm.UserSelectionPostNotify += OnSelection;
            else if (drw != null) drw.UserSelectionPostNotify += OnSelection;
            else return;
            hookedDoc = doc;
        }

        void UnhookDoc()
        {
            object doc = hookedDoc;
            hookedDoc = null;
            if (doc == null) return;
            try
            {
                PartDoc part = doc as PartDoc;
                AssemblyDoc asm = doc as AssemblyDoc;
                DrawingDoc drw = doc as DrawingDoc;
                if (part != null) part.UserSelectionPostNotify -= OnSelection;
                else if (asm != null) asm.UserSelectionPostNotify -= OnSelection;
                else if (drw != null) drw.UserSelectionPostNotify -= OnSelection;
            }
            catch (Exception)
            {
                // the document was already closed: nothing left to unhook
            }
        }

        int OnSelection()
        {
            Safe("selection", delegate { Bump("sel"); });
            return 0;
        }

        // ~/.solidworks-api/swpanel/events/sel.json  {"seq": n, "kind": "sel|doc", "time": "..."}
        void Bump(string kind)
        {
            selSeq++;
            Directory.CreateDirectory(EventsDir);
            WriteAtomic(Path.Combine(EventsDir, "sel.json"),
                "{\"schema\": \"swpanel.event/1\", \"seq\": " + selSeq + ", \"kind\": \"" + kind +
                "\", \"time\": \"" + Now() + "\"}");
        }

        // ---------------------------------------------------------------- helpers
        void Heartbeat()
        {
            string rev = "";
            try { rev = sw.RevisionNumber(); } catch (Exception) { }
            WriteAtomic(Path.Combine(AddinDir, "connected.json"),
                "{\"schema\": \"claudesw.addin/1\", \"time\": \"" + Now() + "\", \"pid\": " +
                Process.GetCurrentProcess().Id + ", \"rev\": \"" + Esc(rev) + "\", \"dll\": \"" +
                Esc(Assembly.GetExecutingAssembly().Location) + "\", \"version\": \"" +
                Assembly.GetExecutingAssembly().GetName().Version + "\"}");
            Log("connected, SolidWorks " + rev);
        }

        // one icon per size the CommandManager asks for (20/32/40/64/96/128), drawn here: no image files to ship
        static string[] Icons()
        {
            try
            {
                int[] sizes = { 20, 32, 40, 64, 96, 128 };
                string[] paths = new string[sizes.Length];
                for (int i = 0; i < sizes.Length; i++)
                {
                    int s = sizes[i];
                    paths[i] = Path.Combine(AddinDir, "icon" + s + ".bmp");
                    using (Bitmap b = new Bitmap(s, s))
                    using (Graphics g = Graphics.FromImage(b))
                    using (Font f = new Font("Arial", s * 0.55f, FontStyle.Bold, GraphicsUnit.Pixel))
                    using (SolidBrush orange = new SolidBrush(Color.FromArgb(217, 119, 87)))
                    {
                        g.Clear(Color.White);
                        g.FillEllipse(orange, 1, 1, s - 2, s - 2);
                        StringFormat c = new StringFormat();
                        c.Alignment = StringAlignment.Center;
                        c.LineAlignment = StringAlignment.Center;
                        g.DrawString("C", f, Brushes.White, new RectangleF(0, 0, s, s), c);
                        b.Save(paths[i], ImageFormat.Bmp);
                    }
                }
                return paths;
            }
            catch (Exception e)
            {
                Log("icons: " + e.Message);
                return null;
            }
        }

        static void WriteAtomic(string path, string text)
        {
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, text, new UTF8Encoding(false));
            if (File.Exists(path)) File.Replace(tmp, path, null);
            else File.Move(tmp, path);
        }

        static string Now()
        {
            return DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
        }

        static string Esc(string s)
        {
            return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
        }

        static void Log(string text)
        {
            try
            {
                Directory.CreateDirectory(AddinDir);
                File.AppendAllText(Path.Combine(AddinDir, "addin.log"), Now() + "  " + text + "\r\n",
                    new UTF8Encoding(false));
            }
            catch (Exception)
            {
            }
        }

        delegate void Step();

        static void Safe(string what, Step step)
        {
            try
            {
                step();
            }
            catch (Exception e)
            {
                Log(what + " failed: " + e);
            }
        }
    }
}
