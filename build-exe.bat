@echo off
REM Build ytarr installer and always update Google Drive\exe
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-exe.ps1"
pause
