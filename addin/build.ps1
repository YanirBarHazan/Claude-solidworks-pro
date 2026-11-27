# Build the Claude add-in DLL with the C# compiler that ships with Windows (.NET Framework 4.x).
# No Visual Studio, no admin rights. Output: addin\bin\ClaudeSwAddin.dll + the SolidWorks interop DLLs beside it.
#
#   powershell -ExecutionPolicy Bypass -File addin\build.ps1                 # finds SolidWorks by itself
#   powershell -ExecutionPolicy Bypass -File addin\build.ps1 -SwDir "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS"
#
# Build against the OLDEST SolidWorks you support (e.g. 2019): an add-in built on 2019's interop loads in newer
# versions, not the other way round.

param([string]$SwDir = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-SwDir {
    $p = Get-Process SLDWORKS -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($p -and $p.Path) { return (Split-Path -Parent $p.Path) }
    $best = $null
    Get-ChildItem "HKLM:\SOFTWARE\SolidWorks" -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -match '^SOLIDWORKS (\d{4})$' } | Sort-Object PSChildName |
        ForEach-Object {
            $d = (Get-ItemProperty (Join-Path $_.PSPath "Setup") -ErrorAction SilentlyContinue)."SolidWorks Folder"
            if ($d -and (Test-Path $d) -and -not $best) { $best = $d }   # keep the oldest installed version
        }
    if ($best) { return $best }
    foreach ($d in @("C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS", "C:\Program Files\SolidWorks Corp\SolidWorks")) {
        if (Test-Path $d) { return $d }
    }
    return $null
}

if (-not $SwDir) { $SwDir = Find-SwDir }
if (-not $SwDir) { throw "SolidWorks folder not found: pass -SwDir" }
$redist = Join-Path $SwDir "api\redist"
$interop = @("SolidWorks.Interop.sldworks.dll", "SolidWorks.Interop.swconst.dll", "SolidWorks.Interop.swpublished.dll")
foreach ($n in $interop) {
    if (-not (Test-Path (Join-Path $redist $n))) { throw "missing $n in $redist" }
}

$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "csc.exe not found at $csc (.NET Framework 4.x 64-bit)" }

$bin = Join-Path $here "bin"
New-Item -ItemType Directory -Force $bin | Out-Null
$refs = $interop | ForEach-Object { "/reference:" + (Join-Path $redist $_) }
$out = Join-Path $bin "ClaudeSwAddin.dll"
& $csc /nologo /target:library /platform:x64 /optimize+ "/out:$out" @refs /reference:System.Drawing.dll `
    (Join-Path $here "ClaudeSwAddin.cs")
if ($LASTEXITCODE -ne 0) { throw "build failed (csc exit $LASTEXITCODE)" }
foreach ($n in $interop) { Copy-Item (Join-Path $redist $n) $bin -Force }

Write-Host "  [OK]  built $out" -ForegroundColor Green
Write-Host "        against $SwDir"
Write-Host "        next: powershell -ExecutionPolicy Bypass -File addin\register.ps1"
