@echo off
REM Start ytarr in the system tray with no console windows.
REM Quotes required — project folder name contains spaces ("yt arr app").
cd /d "%~dp0"
"%SystemRoot%\System32\wscript.exe" //nologo "%~dp0start-ytarr-tray.vbs"
exit /b 0
