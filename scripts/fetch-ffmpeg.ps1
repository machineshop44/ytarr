# Downloads a portable ffmpeg build into tools/ffmpeg (inside the ytarr folder).
# Does not require a global PATH install.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $repo "tools\ffmpeg"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# BtbN shared builds — pinned major channel; update URL if this 404s.
$zipUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
$tmp = Join-Path $env:TEMP ("ytarr-ffmpeg-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$zip = Join-Path $tmp "ffmpeg.zip"

Write-Host "Downloading ffmpeg…"
Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
Write-Host "Extracting…"
Expand-Archive -Path $zip -DestinationPath $tmp -Force

$ffmpeg = Get-ChildItem -Path $tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpeg) { throw "ffmpeg.exe not found in archive" }
$binDir = $ffmpeg.Directory.FullName

foreach ($name in @("ffmpeg.exe", "ffprobe.exe")) {
  $src = Join-Path $binDir $name
  if (Test-Path $src) {
    Copy-Item -LiteralPath $src -Destination (Join-Path $dest $name) -Force
    Write-Host "Installed $name"
  }
}
Get-ChildItem -LiteralPath $binDir -Filter "*.dll" | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $dest $_.Name) -Force
  Write-Host "Installed $($_.Name)"
}

Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Done. ffmpeg is at: $dest"
Write-Host "Leave Settings ffmpeg path empty, or set: tools/ffmpeg/ffmpeg.exe"
