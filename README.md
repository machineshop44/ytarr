# ytarr

Self-hosted Sonarr-style app for YouTube: monitor channels/playlists, download new uploads with **yt-dlp**, and write Plex-friendly per-channel folders with `poster.jpg` artwork.

## Requirements

- Python 3.12+
- Node.js 20+ (for the UI)
- ffmpeg recommended (for merging best video+audio)
- Windows, macOS, or Linux

**yt-dlp** is installed automatically with the backend requirements — no separate Desktop install needed. On a new machine (e.g. your Plex host), `pip install -r backend/requirements.txt` is enough.

HTTPS certificate verification is **on by default**. On Windows, ytarr uses the OS certificate store (so VPN roots like Surfshark work). Settings has an optional “Skip HTTPS certificate checks” toggle only as a last resort on broken guest Wi‑Fi.

## Quick start

### 1. Config

```powershell
cd "C:\Users\machi\Desktop\yt arr app"
copy config.example.yaml config.yaml
```

Edit `config.yaml` if you want a different library folder (default is `./library`). Leave `ytdlp_path` as `yt-dlp` (or empty) to use the bundled module.

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

Port **8199** is ytarr’s default (avoids Readarr’s 8787 and other *arr ports). Change it in `config.yaml` / Settings if you want.

### 3. Frontend (dev)

In a second terminal:

```powershell
cd "C:\Users\machi\Desktop\yt arr app\frontend"
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
- Default format is `bv*+ba/b` merged to `.mkv`.
- Identity is YouTube `video_id`, not title.
