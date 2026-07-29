# Bundled tools (portable)

Put runtime helpers **inside this ytarr folder** so installs do not depend on
Desktop copies of yt-dlp GUIs or a global PATH.

## ffmpeg (required for best quality)

Expected layout:

```text
tools/ffmpeg/ffmpeg.exe
tools/ffmpeg/ffprobe.exe
tools/ffmpeg/libwinpthread-1.dll   (Windows builds often need this)
```

### Option A — fetch script (Windows)

From the ytarr root:

```powershell
.\scripts\fetch-ffmpeg.ps1
```

### Option B — manual

1. Download a Windows ffmpeg build (essentials or full).
2. Copy `ffmpeg.exe` and `ffprobe.exe` (and any required `.dll` files) into `tools/ffmpeg/`.

ytarr auto-detects this folder when Settings → **ffmpeg path** is empty.
You can also set `ffmpeg_path: tools/ffmpeg/ffmpeg.exe` in `config.yaml`.
