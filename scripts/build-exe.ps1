# Build ytarr Windows installer (single setup exe, Arrs Hub style) and
# always copy it to Google Drive\exe (unless -NoCopyToDrive).
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1 -NoCopyToDrive
#   powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1 -SkipFrontend -SkipPyInstaller

param(
  [switch]$SkipFrontend,
  [switch]$SkipPyInstaller,
  [switch]$NoCopyToDrive,
  [string]$DriveExeDir = "G:\My Drive\exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VersionFile = Join-Path $Root "VERSION"
if (-not (Test-Path $VersionFile)) { throw "VERSION file missing at $VersionFile" }
$Version = (Get-Content $VersionFile -Raw).Trim()
if (-not $Version) { throw "VERSION file is empty" }

$Py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
if (-not (Test-Path $Py)) {
  $Py = (py -3.12 -c "import sys; print(sys.executable)").Trim()
}
if (-not $Py -or -not (Test-Path $Py)) {
  throw "Python 3.12 is required to build ytarr"
}

$IsccCandidates = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
  "${env:LocalAppData}\Programs\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
  throw "Inno Setup 6 not found. Install with: winget install JRSoftware.InnoSetup"
}

Write-Host "Python:  $Py"
Write-Host "ISCC:    $Iscc"
Write-Host "Root:    $Root"
Write-Host "Version: $Version"
Write-Host "Drive:   $DriveExeDir $(if ($NoCopyToDrive) { '(skip copy)' } else { '(always update)' })"

if (-not $SkipFrontend) {
  Write-Host "Building frontend..."
  Push-Location (Join-Path $Root "frontend")
  npm run build
  Pop-Location
}

$Spec = Join-Path $Root "packaging\ytarr.spec"
$Dist = Join-Path $Root "dist"
$Work = Join-Path $Root "build"
$OutDir = Join-Path $Dist "ytarr"
$ReleaseDir = Join-Path $Root "release"
$InstallerName = "ytarr-$Version-x64.exe"
$InstallerPath = Join-Path $ReleaseDir $InstallerName

if (-not $SkipPyInstaller) {
  Write-Host "Ensuring build deps..."
  & $Py -m pip install -q -r (Join-Path $Root "backend\requirements.txt")
  & $Py -m pip install -q "pyinstaller>=6.3"

  Write-Host "Running PyInstaller..."
  # PyInstaller writes progress to stderr; don't treat that as a terminating error.
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $Py -m PyInstaller --noconfirm --clean --distpath $Dist --workpath $Work $Spec
  $pyiExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEap
  if ($pyiExit -ne 0) {
    throw "PyInstaller failed with exit code $pyiExit"
  }
}

if (-not (Test-Path (Join-Path $OutDir "ytarr.exe"))) {
  throw "Build failed - ytarr.exe not found in $OutDir (run without -SkipPyInstaller)"
}

# Bundle ffmpeg into the payload the installer packages
$FfmpegSrc = Join-Path $Root "tools\ffmpeg"
$FfmpegDst = Join-Path $OutDir "tools\ffmpeg"
if (Test-Path (Join-Path $FfmpegSrc "ffmpeg.exe")) {
  Write-Host "Copying bundled ffmpeg into payload..."
  New-Item -ItemType Directory -Path $FfmpegDst -Force | Out-Null
  Copy-Item (Join-Path $FfmpegSrc "*") $FfmpegDst -Recurse -Force
} else {
  Write-Host "WARNING: tools\ffmpeg\ffmpeg.exe missing - installer will not include ffmpeg."
}

$Example = Join-Path $Root "config.example.yaml"
if (Test-Path $Example) {
  Copy-Item $Example (Join-Path $OutDir "config.example.yaml") -Force
}

# Strip any accidental user data from the packaging tree
foreach ($name in @("data", "library", "music")) {
  $p = Join-Path $OutDir $name
  if (Test-Path $p) {
    Remove-Item $p -Recurse -Force
  }
}
foreach ($junk in @("config.yaml", "ytarr-tray.log", "README.txt", "Start ytarr.bat", "Diagnose ytarr.bat")) {
  $p = Join-Path $OutDir $junk
  if (Test-Path $p) { Remove-Item $p -Force }
}

$DebugBat = @"
@echo off
cd /d "%~dp0"
echo ytarr debug mode - errors will show in this window.
"%~dp0ytarr.exe" --debug --open-ui
echo.
echo Exit code: %ERRORLEVEL%
echo.
echo If it failed, also check:
echo   %TEMP%\ytarr-boot.log
echo   %~dp0data\ytarr-tray.log
pause
"@
Set-Content -Path (Join-Path $OutDir "Diagnose ytarr.bat") -Value $DebugBat -Encoding ASCII

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

Write-Host "Compiling installer with Inno Setup..."
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Iscc "/DMyAppVersion=$Version" (Join-Path $Root "packaging\ytarr.iss")
$isccExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($isccExit -ne 0) {
  throw "Inno Setup failed with exit code $isccExit"
}
if (-not (Test-Path $InstallerPath)) {
  throw "Installer not found at $InstallerPath"
}

$SizeMb = [math]::Round((Get-Item $InstallerPath).Length / 1MB, 1)
Write-Host "Built installer: $InstallerPath ($SizeMb MB)"

if (-not $NoCopyToDrive) {
  if (-not (Test-Path $DriveExeDir)) {
    throw "Drive exe folder not found: $DriveExeDir (use -NoCopyToDrive to skip)"
  }
  # Replace old portable folder if present
  $OldPortable = Join-Path $DriveExeDir "ytarr"
  if (Test-Path $OldPortable) {
    Write-Host "Removing old portable folder $OldPortable ..."
    Remove-Item $OldPortable -Recurse -Force
  }
  # Remove previous ytarr-*-x64.exe installers on Drive so only the latest remains
  Get-ChildItem -Path $DriveExeDir -Filter "ytarr-*-x64.exe" -ErrorAction SilentlyContinue |
    Remove-Item -Force
  $Dest = Join-Path $DriveExeDir $InstallerName
  Write-Host "Updating Google Drive exe folder: $Dest ..."
  Copy-Item $InstallerPath $Dest -Force
  Write-Host "Updated $InstallerName in $DriveExeDir"
}

Write-Host "Done."
