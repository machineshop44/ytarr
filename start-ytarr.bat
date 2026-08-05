@echo off
REM Prefer packaged ytarr.exe when present; otherwise tray via pythonw.
cd /d "%~dp0"
if exist "%~dp0dist\ytarr\ytarr.exe" (
  start "" "%~dp0dist\ytarr\ytarr.exe" --open-ui
  exit /b 0
)
if exist "%~dp0ytarr.exe" (
  start "" "%~dp0ytarr.exe" --open-ui
  exit /b 0
)
"%SystemRoot%\System32\wscript.exe" //nologo "%~dp0start-ytarr-tray.vbs"
exit /b 0
