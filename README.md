# ytarr

Self-hosted Sonarr-style app for YouTube: monitor channels/playlists, download new uploads with **yt-dlp**, and write Plex-friendly per-channel folders with `poster.jpg` artwork.

## Requirements

- Python 3.12+
- Node.js 20+ (for building the UI, and for YouTube JS extraction at runtime)
- **ffmpeg** bundled under `tools/ffmpeg/` (run `scripts\fetch-ffmpeg.ps1` on a new machine). Without it, ytarr falls back to single-file downloads.
- Windows, macOS, or Linux

**Portable layout:** keep runtime helpers inside the ytarr folder (`tools/`, `data/`, `assets/`). Do not rely on a separate Desktop yt-dlp GUI install.

**yt-dlp** is installed automatically with the backend requirements — no separate Desktop install needed. On a new machine: `pip install -r backend/requirements.txt`, then fetch ffmpeg as above.

HTTPS certificate verification is **on by default**. On Windows, ytarr uses the OS certificate store (so VPN roots like Surfshark work). Settings has an optional “Skip HTTPS certificate checks” toggle only as a last resort on broken guest Wi‑Fi.

## Windows installer (Arr-style)

Build a single setup exe (same idea as Arrs Hub / Sonarr):

```bat
build-exe.bat
```

Or:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
```

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

Output: `release\ytarr-<version>-x64.exe`, and the build always updates `G:\My Drive\exe\` (use `-NoCopyToDrive` to skip). Run the installer → Start Menu / Desktop shortcut → system tray app on port 8199. User data (`config.yaml`, `data\`, libraries) stays under the install folder and is kept on upgrade/uninstall.

## Quick start (dev / source)

### 1. Config

```powershell
cd <path-to-ytarr>
copy config.example.yaml config.yaml
.\scripts\fetch-ffmpeg.ps1
```

Edit `config.yaml` if you want a different library folder (default is `./library` under the app). Leave `ytdlp_path` as `yt-dlp` and `ffmpeg_path` as `tools/ffmpeg/ffmpeg.exe` (or empty for auto-detect of the bundled tools folder). All relative paths resolve from the app folder.

### 2. Backend

```powershell
py -m pip install -r backend\requirements.txt
cd backend
py run.py
```

API runs at [http://127.0.0.1:8199](http://127.0.0.1:8199) · docs at `/docs`.

ytarr runs yt-dlp as `python -m yt_dlp` by default. Optional: set an absolute path to `yt-dlp.exe` in Settings / `ytdlp_path` if you prefer an external binary.

### Start / stop (Windows)

ytarr runs in the **system tray** (like Sonarr/Radarr) — no console windows.

| Action | How |
|--------|-----|
| **Start** | Double-click **`Start ytarr`** (green play icon). If missing, run `create-shortcuts.bat` once. (`start-ytarr.bat` still works; Windows always shows the generic cmd icon on `.bat` files.) |
| **Open UI** | Browser opens automatically, or right-click the green tray icon → **Open ytarr** |
| **Stop** | Tray icon → **Quit**, or double-click **`Stop ytarr`** |

If ytarr is already running, Start just opens the UI again (won’t spawn duplicates).

Look for the green play icon near the clock (Windows may hide it under the ^ overflow arrow).

Port **8199** is ytarr’s default (avoids Readarr’s 8787 and other *arr ports). The API binds **`0.0.0.0` by default** so LAN clients and a WAN port-forward (e.g. `67.x:8199` → Plex PC) can reach it — same idea as Arrs Hub. Opt into localhost-only with `host: 127.0.0.1` in `config.yaml` (restart after change).

### 3. Frontend (dev)

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173) (proxies `/api` to the backend).

### 4. Optional: serve UI from the API

```powershell
cd frontend
npm run build
```

Then open [http://127.0.0.1:8199](http://127.0.0.1:8199) — the API serves `frontend/dist`.

## How it works

1. **Add a channel or playlist URL** on Sources.
2. On first add, current videos are marked **seen** (no history dump).
3. Periodic monitor (default every 30 minutes) finds **new** uploads → **wanted**.
4. Download worker runs **yt-dlp** into your library root.
5. Channel avatar is saved as `{Channel}/poster.jpg` (and banner as `fanart.jpg` when available).

### Library layout

```text
library/
  Channel Name/
    poster.jpg
    fanart.jpg
    2026-07-28 - Video Title [dQw4w9wgXcQ].mkv
```

## Plex setup

1. Keep **Sonarr** for real TV only — do not add YouTube channels there.
2. Create a **separate** Plex library pointed at ytarr’s library root.
3. Use **Local Media Assets / Personal Media** (turn off TVDB/TMDB scrapers) so each channel folder uses `poster.jpg` instead of matching Dropout (etc.) to the wrong online show.
4. Workout day-by-day playlists that Arrs Hub needs as separate titles can stay in a **Home Videos** library.

## Main UI pages

| Page | Purpose |
|------|---------|
| Dashboard | Counts, yt-dlp health |
| Sources | Add/monitor channels, refresh artwork |
| Library | Browse by status, retry/ignore |
| Queue | Download progress |
| Settings | Library path, format, poll interval |

## Notes

- v1 monitors **new uploads only** (no “download last N” backfill UI). Use Library → Seen → Download for one-offs.
- Default format is `bv*+ba/b` (merged to `.mkv` when **ffmpeg** is installed). If ffmpeg is missing, ytarr automatically uses single-file `b` so downloads still work.
- Identity is YouTube `video_id`, not title.
