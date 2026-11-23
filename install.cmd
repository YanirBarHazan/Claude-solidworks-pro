@echo off
rem Double-click: installs or updates Claude x SolidWorks and the Claude tab inside SolidWorks.
title Claude x SolidWorks - install
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
