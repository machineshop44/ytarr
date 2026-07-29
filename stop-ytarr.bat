@echo off
REM Stop ytarr tray/server without leaving consoles open.
REM Single-line PowerShell avoids caret-continuation breakage with spaces in the path.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(8199); foreach($port in $ports){ Get-NetTCPConnection -LocalPort $port -State Listen -EA SilentlyContinue | ForEach-Object { try{Stop-Process -Id $_.OwningProcess -Force -EA Stop}catch{} } }; Get-CimInstance Win32_Process -EA SilentlyContinue | Where-Object { $_.CommandLine -match 'tray_app\.py|yt arr app\\backend\\run\.py' } | ForEach-Object { try{Stop-Process -Id $_.ProcessId -Force}catch{} }"
exit /b 0
