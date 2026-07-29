@echo off
REM Create Start/Stop shortcuts that use the ytarr icon (batch files can't show custom icons).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\create-shortcuts.ps1"
exit /b %ERRORLEVEL%
