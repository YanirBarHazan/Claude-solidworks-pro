# Kept for old links: updating is the same as installing. Runs install.ps1 (next to this file, or from GitHub).
$local = if ($PSScriptRoot) { Join-Path $PSScriptRoot "install.ps1" } else { $null }
if ($local -and (Test-Path $local)) { & $local }
else { Invoke-RestMethod https://raw.githubusercontent.com/YanirBarHazan/Claude-solidworks-pro/main/install.ps1 | Invoke-Expression }
