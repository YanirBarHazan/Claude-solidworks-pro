# Register (or remove) the Claude add-in with SolidWorks.
#
#   powershell -ExecutionPolicy Bypass -File addin\register.ps1                    # this Windows user, NO admin
#   powershell -ExecutionPolicy Bypass -File addin\register.ps1 -Scope Machine     # all users, needs "Run as admin"
#   powershell -ExecutionPolicy Bypass -File addin\register.ps1 -Unregister        # remove (same -Scope as before)
#
# Does NOT use regasm: it writes the same COM keys regasm would, so the user scope can go to HKCU.
#   User:    HKCU\Software\Classes\CLSID\{GUID} + ProgID     (COM, per user - Windows supports this)
#            HKCU\Software\SolidWorks\Addins\{GUID}          (THE OPEN QUESTION: does SolidWorks read it here?)
#            HKCU\Software\SolidWorks\AddInsStartup\{GUID}   (load at start - always per user)
#   Machine: the same under HKLM (the documented way), AddInsStartup stays in HKCU.
# test_registration.py answers the open question on your PC.
#
# Files: copies addin\bin to %USERPROFILE%\.solidworks-api\addin\bin (close SolidWorks first when updating:
# a loaded DLL is locked) and writes config.txt there with the Python that starts the Claude tab.

param(
    [ValidateSet("User", "Machine")][string]$Scope = "User",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"

$Guid = "{DDC81893-703C-404D-BFFD-74D6781C5148}"     # = [Guid] in ClaudeSwAddin.cs
$ProgId = "ClaudeSw.Addin"
$Title = "Claude for SolidWorks"
$Desc = "Opens the Claude chat tab in the Task Pane"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$home_ = Join-Path $env:USERPROFILE ".solidworks-api"
$dest = Join-Path $home_ "addin\bin"
$dll = Join-Path $dest "ClaudeSwAddin.dll"

function Step($ok, $text) {
    if ($ok) { Write-Host "  [OK]  $text" -ForegroundColor Green } else { Write-Host "  [!!]  $text" -ForegroundColor Yellow }
}

if (-not [Environment]::Is64BitProcess) { throw "run this from 64-bit PowerShell (SolidWorks is 64-bit)" }
$root = if ($Scope -eq "Machine") { "HKLM:" } else { "HKCU:" }
if ($Scope -eq "Machine") {
    $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { throw "-Scope Machine needs an elevated PowerShell (Run as administrator)" }
}
$classes = "$root\Software\Classes"
$swAddins = "$root\Software\SolidWorks\Addins\$Guid"
$startup = "HKCU:\Software\SolidWorks\AddInsStartup\$Guid"

if ($Unregister) {
    foreach ($k in @("$classes\CLSID\$Guid", "$classes\$ProgId", $swAddins, $startup)) {
        if (Test-Path $k) { Remove-Item $k -Recurse -Force }
    }
    Step $true "removed ($Scope). Files in $dest stay; delete them after closing SolidWorks if you want."
    exit 0
}

# 1. files
$src = Join-Path $here "bin\ClaudeSwAddin.dll"
if (-not (Test-Path $src)) { throw "build first: powershell -ExecutionPolicy Bypass -File addin\build.ps1" }
New-Item -ItemType Directory -Force $dest | Out-Null
try {
    Copy-Item (Join-Path $here "bin\*.dll") $dest -Force
} catch {
    throw "could not copy the DLLs (SolidWorks has the old one loaded?). Close SolidWorks and run again."
}
Step $true "files in $dest"

# 2. config.txt: which Python starts the tab (the add-in only launches it)
function Find-Pythonw {
    foreach ($c in @("py", "python")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $cmd -or $cmd.Source -like "*WindowsApps*") { continue }
        $a = if ($c -eq "py") { @("-3", "-c") } else { @("-c") }
        try {
            $exe = & $cmd.Source @a "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) {
                $w = Join-Path (Split-Path -Parent $exe.Trim()) "pythonw.exe"
                if (Test-Path $w) { return $w }
            }
        } catch { }
    }
    return $null
}
$pyw = Find-Pythonw
$script = Join-Path $home_ "app\scripts\swpanel_taskpane.py"
[IO.File]::WriteAllText((Join-Path $home_ "addin\config.txt"), "pythonw=$pyw`r`nscript=$script`r`n",
    (New-Object Text.UTF8Encoding $false))
Step ([bool]$pyw) $(if ($pyw) { "Python for the tab: $pyw" } else { "pythonw.exe not found: the button cannot start the tab" })
Step (Test-Path $script) $(if (Test-Path $script) { "Claude tab installed" } else { "Claude tab not installed yet: run install.ps1 first" })

# 3. COM class (what regasm /codebase writes, by hand)
$asm = [Reflection.AssemblyName]::GetAssemblyName($dll)
$codeBase = "file:///" + ($dll -replace "\\", "/")
$clsid = "$classes\CLSID\$Guid"
New-Item -Force $clsid -Value $ProgId | Out-Null
New-Item -Force "$clsid\ProgId" -Value $ProgId | Out-Null
New-Item -Force "$clsid\Implemented Categories\{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}" | Out-Null
foreach ($k in @("$clsid\InprocServer32", "$clsid\InprocServer32\$($asm.Version)")) {
    if ($k -like "*InprocServer32") {
        New-Item -Force $k -Value "mscoree.dll" | Out-Null
        New-ItemProperty -Force $k -Name ThreadingModel -Value "Both" | Out-Null
    } else {
        New-Item -Force $k | Out-Null
    }
    New-ItemProperty -Force $k -Name Class -Value $ProgId | Out-Null
    New-ItemProperty -Force $k -Name Assembly -Value $asm.FullName | Out-Null
    New-ItemProperty -Force $k -Name RuntimeVersion -Value "v4.0.30319" | Out-Null
    New-ItemProperty -Force $k -Name CodeBase -Value $codeBase | Out-Null
}
New-Item -Force "$classes\$ProgId" -Value $ProgId | Out-Null
New-Item -Force "$classes\$ProgId\CLSID" -Value $Guid | Out-Null
Step $true "COM class registered ($Scope)"

# 4. SolidWorks add-in list + load at start
New-Item -Force $swAddins | Out-Null
New-ItemProperty -Force $swAddins -Name "(Default)" -PropertyType DWord -Value 1 | Out-Null
New-ItemProperty -Force $swAddins -Name Title -Value $Title | Out-Null
New-ItemProperty -Force $swAddins -Name Description -Value $Desc | Out-Null
New-Item -Force $startup | Out-Null
New-ItemProperty -Force $startup -Name "(Default)" -PropertyType DWord -Value 1 | Out-Null
Step $true "SolidWorks add-in keys ($swAddins)"

Write-Host ""
Write-Host "  next: python addin\test_registration.py   (then restart SolidWorks and run it again with --after-restart)"
