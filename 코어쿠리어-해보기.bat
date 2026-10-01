@echo off
rem Core Courier: double-click to play the latest merged version. (logic: tools/dev/core-courier-play.ps1)
where pwsh >nul 2>nul
if %errorlevel%==0 (set PSH=pwsh) else (set PSH=powershell)
%PSH% -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools/dev/core-courier-play.ps1"
if errorlevel 1 pause
