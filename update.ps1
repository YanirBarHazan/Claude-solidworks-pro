# Update the solidworks-api skill (and the Claude tab inside SolidWorks) to the latest version on GitHub.
#
#   powershell -ExecutionPolicy Bypass -File update.ps1
#   or, without cloning the repo:
#   irm https://raw.githubusercontent.com/YanirBarHazan/Claude-solidworks-pro/main/update.ps1 -OutFile $env:TEMP\swupd.ps1
#   powershell -ExecutionPolicy Bypass -File $env:TEMP\swupd.ps1
#
# What it does:
#   1. stops the running Claude tab watcher and the fast-command worker (they keep the OLD code in memory,
#      which is why the tab stays old even after the files are replaced)
#   2. downloads the latest skill from GitHub and replaces %USERPROFILE%\.claude\skills\solidworks-api
#      (the old folder is moved to ~\.solidworks-api\backups\ - not left in .claude\skills, where Claude Code would
#      load it as a second skill; your chats/settings in ~\.solidworks-api are untouched)
#   3. starts the watcher again, so the new tab appears the next time SolidWorks starts
#
# Close SolidWorks before running it (or restart SolidWorks afterwards): an open SolidWorks keeps the old tab.

param(
    [string]$SkillDir = (Join-Path $env:USERPROFILE ".claude\skills\solidworks-api"),
    [string]$Branch = "main",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repo = "YanirBarHazan/Claude-solidworks-pro"
$panelDir = Join-Path $env:USERPROFILE ".solidworks-api\swpanel"

Write-Host "== Claude x SolidWorks: update ==" -ForegroundColor Cyan
Write-Host "skill folder: $SkillDir"

# 1. stop the old tab watcher + worker
if (Test-Path $panelDir) { New-Item -ItemType File -Force (Join-Path $panelDir "taskpane.stop") | Out-Null }
$old = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match "swpanel_taskpane|swpanel_worker" }
foreach ($p in $old) {
    Write-Host "stopping old panel process $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
$swOpen = @(Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue).Count -gt 0

# 2. download + replace
$tmp = Join-Path $env:TEMP ("sw-skill-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $tmp | Out-Null
$zip = Join-Path $tmp "repo.zip"
Write-Host "downloading $repo ($Branch) ..."
Invoke-WebRequest -UseBasicParsing "https://codeload.github.com/$repo/zip/refs/heads/$Branch" -OutFile $zip
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$new = Get-ChildItem -Directory $tmp | ForEach-Object { Join-Path $_.FullName "skill\solidworks-api" } |
    Where-Object { Test-Path (Join-Path $_ "SKILL.md") } | Select-Object -First 1
if (-not $new) { throw "skill/solidworks-api not found in the download" }

if (Test-Path $SkillDir) {
    $bakRoot = Join-Path $env:USERPROFILE ".solidworks-api\backups"
    New-Item -ItemType Directory -Force $bakRoot | Out-Null
    $bak = Join-Path $bakRoot ("solidworks-api-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Move-Item $SkillDir $bak
    Write-Host "old version kept in $bak"
}
New-Item -ItemType Directory -Force (Split-Path $SkillDir) | Out-Null
Copy-Item $new $SkillDir -Recurse
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $panelDir) { Remove-Item (Join-Path $panelDir "taskpane.stop") -ErrorAction SilentlyContinue }
Write-Host "skill updated." -ForegroundColor Green

# 3. restart the watcher (adds the new tab whenever SolidWorks starts)
if (-not $NoRestart) {
    $pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if (-not $pyw) {
        $py = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($py) { $pyw = Join-Path (Split-Path $py) "pythonw.exe" }
    }
    if ($pyw -and (Test-Path $pyw)) {
        Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $SkillDir 'scripts\swpanel_taskpane.py')`" watch" -WindowStyle Hidden
        Write-Host "Claude tab watcher restarted with the new version."
    } else {
        Write-Host "pythonw not found: start the tab by hand: pythonw `"$SkillDir\scripts\swpanel_taskpane.py`" watch" -ForegroundColor Yellow
    }
}

if ($swOpen) {
    Write-Host "SolidWorks is open: close it and open it again to get the new Claude tab." -ForegroundColor Yellow
}
Write-Host "Also restart any open Claude Code session so it loads the new skill."
