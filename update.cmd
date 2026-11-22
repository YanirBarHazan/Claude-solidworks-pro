@echo off
rem Double-click to update the solidworks-api skill and the Claude tab in SolidWorks.
title Claude x SolidWorks - update
echo Close SolidWorks before continuing.
pause
set "PS1=%~dp0update.ps1"
if exist "%PS1%" goto run
set "PS1=%TEMP%\swupd.ps1"
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; $b='https://raw.githubusercontent.com/YanirBarHazan/Claude-solidworks-pro/'; try { irm ($b+'main/update.ps1') -OutFile $env:TEMP\swupd.ps1 } catch { irm ($b+'claude/clever-lamport-869l63/update.ps1') -OutFile $env:TEMP\swupd.ps1 }"
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
echo.
pause
