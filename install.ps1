# Claude x SolidWorks - install or update everything in one run (no admin rights).
#
# Easiest: Windows key + R, paste, Enter:
#   powershell -ExecutionPolicy Bypass -NoExit -c "irm https://raw.githubusercontent.com/YanirBarHazan/Claude-solidworks-pro/main/install.ps1 | iex"
# Or: download the repository ZIP, extract it, double-click install.cmd.
#
# Steps (each prints one line):
#   1. Python 3   - installs it with winget if missing
#   2. Claude Code - installs it with the official installer if neither it nor the Claude app's copy is found
#   3. the skill  - latest version to %USERPROFILE%\.claude\skills\solidworks-api
#                   (an older copy goes to ~\.solidworks-api\backups\; chats and settings are kept)
#   4. the Claude tab in SolidWorks - scripts\install_panel.py: pywin32, stops an old tab, starts the new one,
#                   and starts it at every Windows sign-in
# Re-run it any time to update.

param(
    [string]$SkillDir = (Join-Path $env:USERPROFILE ".claude\skills\solidworks-api"),
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = "YanirBarHazan/Claude-solidworks-pro"
$linkedin = "https://www.linkedin.com/in/yanir-hazan"

function Step($ok, $text) {
    if ($ok) { Write-Host "  [OK]  $text" -ForegroundColor Green } else { Write-Host "  [!!]  $text" -ForegroundColor Yellow }
}
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Find-Python {
    foreach ($c in @("py", "python")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if (-not $cmd -or $cmd.Source -like "*WindowsApps*") { continue }   # skip the Microsoft Store stub
        $args_ = if ($c -eq "py") { @("-3", "-c") } else { @("-c") }
        try {
            $exe = & $cmd.Source @args_ "import sys; print(sys.executable) if sys.version_info >= (3, 9) else None" 2>$null
            if ($LASTEXITCODE -eq 0 -and $exe) { return $exe.Trim() }
        } catch { }
    }
    $hit = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return $null
}

Write-Host ""
Write-Host "== Claude x SolidWorks: install / update ==" -ForegroundColor Cyan
Write-Host ""

# 1. Python
$py = Find-Python
if (-not $py) {
    Write-Host "  installing Python 3.12 (a minute) ..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Null
        Refresh-Path
        $py = Find-Python
    }
}
if (-not $py) {
    Step $false "Python not found. Install it from python.org/downloads (tick 'Add python.exe to PATH') and run this again."
    Start-Process "https://www.python.org/downloads/"
    return
}
Step $true "Python: $py"

# 2. Claude Code (the tab runs it in the background)
$claude = Get-ChildItem "$env:APPDATA\Claude\claude-code\*\*\claude.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $claude) { $claude = Get-Command claude -ErrorAction SilentlyContinue }
if (-not $claude -and (Test-Path "$env:USERPROFILE\.local\bin\claude.exe")) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
if (-not $claude) {
    Write-Host "  installing Claude Code (official installer) ..."
    try { Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression } catch { }
    Refresh-Path
    if (Test-Path "$env:USERPROFILE\.local\bin\claude.exe") { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
}
Step ([bool]$claude) $(if ($claude) { "Claude Code" } else { "Claude Code not installed: get the Claude app from claude.com/download, then run this again" })

# 3. the skill (from this folder when run from an extracted ZIP / clone, else downloaded)
$src = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "skill\solidworks-api\SKILL.md"))) {
    $src = Join-Path $PSScriptRoot "skill\solidworks-api"
} else {
    $tmp = Join-Path $env:TEMP ("sw-skill-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$repo/zip/refs/heads/$Branch" -OutFile "$tmp\repo.zip"
    Expand-Archive "$tmp\repo.zip" -DestinationPath $tmp -Force
    $src = Get-ChildItem -Directory $tmp | ForEach-Object { Join-Path $_.FullName "skill\solidworks-api" } |
        Where-Object { Test-Path (Join-Path $_ "SKILL.md") } | Select-Object -First 1
    if (-not $src) { throw "skill/solidworks-api not found in the download" }
}
$same = (Test-Path $SkillDir) -and ((Resolve-Path $SkillDir).Path -eq (Resolve-Path $src).Path)
if (-not $same) {
    if (Test-Path $SkillDir) {
        $bak = Join-Path $env:USERPROFILE (".solidworks-api\backups\solidworks-api-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        New-Item -ItemType Directory -Force (Split-Path $bak) | Out-Null
        Move-Item $SkillDir $bak
    }
    New-Item -ItemType Directory -Force (Split-Path $SkillDir) | Out-Null
    Copy-Item $src $SkillDir -Recurse
}
$ver = (Get-Content (Join-Path $SkillDir "VERSION") -ErrorAction SilentlyContinue | Select-Object -First 1)
Step $true "skill $ver -> $SkillDir"

# 4. the Claude tab
Write-Host ""
& $py (Join-Path $SkillDir "scripts\install_panel.py")
$tabOk = ($LASTEXITCODE -eq 0)

Write-Host ""
if ($tabOk) {
    Write-Host "Done. Open SolidWorks: the Claude tab is on the right (Task Pane)." -ForegroundColor Green
    Write-Host "First time only: click 'connect to Claude' in the tab. Then just type what you need, Hebrew or English."
} else {
    Write-Host "Almost done - see the [!!] / FAIL lines above. Help: github.com/$repo/blob/main/docs/troubleshooting.md" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Feedback, ideas, or a custom version for your company: $linkedin" -ForegroundColor Cyan
Write-Host ""
