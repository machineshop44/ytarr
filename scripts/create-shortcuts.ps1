# Creates Start / Stop shortcuts with the ytarr brand icon.
# .bat files always show the generic cmd icon on Windows; .lnk can use ytarr.ico.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$ico = Join-Path $repo "assets\ytarr.ico"
if (-not (Test-Path $ico)) {
  Write-Error "Missing icon: $ico"
}

$shell = New-Object -ComObject WScript.Shell

function New-YtarrShortcut {
  param(
    [string]$Name,
    [string]$Target,
    [string]$Arguments = "",
    [string]$Description,
    [int]$WindowStyle = 1
  )
  $lnkPath = Join-Path $repo $Name
  $sc = $shell.CreateShortcut($lnkPath)
  $sc.TargetPath = $Target
  $sc.Arguments = $Arguments
  $sc.WorkingDirectory = $repo
  $sc.IconLocation = "$ico,0"
  $sc.Description = $Description
  $sc.WindowStyle = $WindowStyle
  $sc.Save()
  Write-Host "Created $Name"
}

$wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$startVbs = Join-Path $repo "start-ytarr-tray.vbs"
$stopBat = Join-Path $repo "stop-ytarr.bat"

New-YtarrShortcut -Name "Start ytarr.lnk" -Target $wscript -Arguments "//nologo `"$startVbs`"" -Description "Start ytarr in the system tray"
New-YtarrShortcut -Name "Stop ytarr.lnk" -Target $stopBat -Description "Stop ytarr" -WindowStyle 7

Write-Host "Done. Double-click 'Start ytarr' for the green play icon (matches tray / favicon)."
