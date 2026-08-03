"""ytarr system-tray launcher (no console window)."""
from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

# Resolve imports before other app imports (source tree only)
if not getattr(sys, "frozen", False):
    BACKEND_DIR = Path(__file__).resolve().parent
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

from app.paths import project_root, resource_path  # noqa: E402

PROJECT_ROOT = project_root()
LOG_PATH = PROJECT_ROOT / "data" / "ytarr-tray.log"
OPEN_UI_REQUEST = PROJECT_ROOT / "data" / "open-ui.request"
BROWSER_COOLDOWN_FILE = PROJECT_ROOT / "data" / "browser-open.cooldown"

# Cross-process + in-process cooldown (watchdogs can spawn us every ~1s)
_BROWSER_COOLDOWN_SEC = 30.0
_last_browser_open = 0.0
_browser_lock = threading.Lock()
_instance_mutex = None  # keep handle alive for process lifetime


def _log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
    except Exception:
        pass


def _caller_context() -> str:
    """Help identify what is re-launching ytarr.exe (Arrs Hub watchdog, etc.)."""
    bits = [f"pid={os.getpid()}"]
    try:
        bits.append(f"ppid={os.getppid()}")
    except Exception:
        pass
    try:
        bits.append(f"cwd={os.getcwd()}")
    except Exception:
        pass
    if len(sys.argv) > 1:
        bits.append(f"argv={sys.argv[1:]}")
    return " ".join(bits)


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _cooldown_allows_open() -> bool:
    """Shared filesystem cooldown so every new process respects prior opens."""
    global _last_browser_open
    now = time.monotonic()
    now_wall = time.time()
    with _browser_lock:
        if _last_browser_open and (now - _last_browser_open) < _BROWSER_COOLDOWN_SEC:
            return False
        try:
            if BROWSER_COOLDOWN_FILE.exists():
                age = now_wall - BROWSER_COOLDOWN_FILE.stat().st_mtime
                if age < _BROWSER_COOLDOWN_SEC:
                    return False
        except OSError:
            pass
        _last_browser_open = now
        try:
            BROWSER_COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
            BROWSER_COOLDOWN_FILE.write_text(str(now_wall), encoding="utf-8")
        except OSError:
            pass
        return True


def _open_browser(url: str, *, reason: str) -> bool:
    """Open the UI at most once per cooldown window (in-process + on disk)."""
    if not _cooldown_allows_open():
        _log(f"skip browser open ({reason}); cooldown active")
        return False
    _log(f"open browser ({reason}): {url}")
    try:
        webbrowser.open(url)
    except Exception:
        _log("browser open failed:\n" + traceback.format_exc())
        return False
    return True


def _request_open_ui() -> None:
    """Ask the already-running tray instance to open the UI (no browser from this process)."""
    try:
        OPEN_UI_REQUEST.parent.mkdir(parents=True, exist_ok=True)
        OPEN_UI_REQUEST.write_text(str(time.time()), encoding="utf-8")
        _log("signaled running instance to open UI")
    except OSError:
        _log("failed to write open-ui request:\n" + traceback.format_exc())


def _acquire_single_instance() -> bool:
    """Return True if this process owns the ytarr instance lock."""
    global _instance_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Per-user session mutex (matches per-user installer)
        handle = kernel32.CreateMutexW(None, False, "Local\\ytarr_tray_single_instance")
        if not handle:
            return True
        _instance_mutex = handle
        ERROR_ALREADY_EXISTS = 183
        return kernel32.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:
        _log("single-instance mutex failed:\n" + traceback.format_exc())
        return True


def _make_icon():
    """Brand mark: green play circle (same as assets/ytarr.ico / favicon)."""
    from PIL import Image, ImageDraw

    for name in ("ytarr.png", "ytarr.ico"):
        path = resource_path("assets", name)
        if not path.exists():
            continue
        try:
            with Image.open(path) as im:
                return im.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            continue

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, size - 3, size - 3), fill=(35, 134, 54, 255))
    draw.polygon([(24, 18), (24, 46), (48, 32)], fill=(255, 255, 255, 255))
    return img


def _ui_url() -> str:
    from app.config import get_config

    cfg = get_config()
    host = "127.0.0.1" if cfg.host in {"0.0.0.0", "::"} else cfg.host
    return f"http://{host}:{cfg.port}"


def main() -> None:
    from app.config import get_config, record_listen_bind, config_file_path

    cfg = get_config()
    url = _ui_url()
    _log(
        f"start host={cfg.host} port={cfg.port} config={config_file_path()} "
        f"frozen={getattr(sys, 'frozen', False)} {_caller_context()}"
    )

    # pythonw / windowed exe has no stdout/stderr — uvicorn color logging crashes without this
    if sys.stdout is None:
        sys.stdout = open(LOG_PATH, "a", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = sys.stdout

    owns_lock = _acquire_single_instance()
    port_busy = _port_open("127.0.0.1", cfg.port)

    # Another ytarr already owns the tray / server — never open Chrome from this
    # process (watchdogs may spawn us every second; that was the tab storm).
    if not owns_lock or port_busy:
        _log(
            f"already running (owns_lock={owns_lock} port_busy={port_busy}) - "
            "signal primary instance only, no browser from this process"
        )
        # Only honor an explicit user request (Start Menu / --open-ui), not watchdog spawns.
        if "--open-ui" in sys.argv or os.environ.get("YTARR_OPEN_UI", "").strip() in {
            "1",
            "true",
            "yes",
        }:
            _request_open_ui()
        return

    import pystray
    from pystray import MenuItem as Item
    import uvicorn

    # Frozen builds import the app object directly (string import breaks under PyInstaller)
    if getattr(sys, "frozen", False):
        from app.main import app as fastapi_app

        app_ref = fastapi_app
    else:
        app_ref = "app.main:app"

    listen_host = (cfg.host or "").strip() or "0.0.0.0"
    listen_port = int(cfg.port)
    record_listen_bind(listen_host, listen_port)
    _log(f"binding uvicorn host={listen_host} port={listen_port}")

    server_config = uvicorn.Config(
        app_ref,
        host=listen_host,
        port=listen_port,
        log_level="warning",
        access_log=False,
        use_colors=False,
    )
    server = uvicorn.Server(server_config)

    def run_server() -> None:
        try:
            server.run()
        except Exception:
            _log("server crashed:\n" + traceback.format_exc())

    thread = threading.Thread(target=run_server, name="ytarr-uvicorn", daemon=True)
    thread.start()

    for _ in range(80):
        if _port_open("127.0.0.1", cfg.port):
            break
        time.sleep(0.1)
    else:
        _log("server failed to listen in time")
        return

    _log("listening - starting tray icon")

    def open_ui(icon=None, item=None) -> None:  # noqa: ARG001
        _open_browser(url, reason="tray-open")

    def open_activity(icon=None, item=None) -> None:  # noqa: ARG001
        _open_browser(f"{url}/activity", reason="tray-activity")

    def quit_app(icon, item=None) -> None:  # noqa: ARG001
        _log("quit requested")
        server.should_exit = True
        icon.stop()

    # No default=True: left-click must not auto-fire Open (avoids click/focus tab storms).
    icon = pystray.Icon(
        name="ytarr",
        icon=_make_icon(),
        title=f"ytarr — bind {listen_host}:{listen_port}",
        menu=pystray.Menu(
            Item("Open ytarr", open_ui),
            Item("Activity", open_activity),
            Item("Quit", quit_app),
        ),
    )

    stop_watch = threading.Event()

    def _watch_open_requests() -> None:
        last_seen = 0.0
        try:
            if OPEN_UI_REQUEST.exists():
                last_seen = OPEN_UI_REQUEST.stat().st_mtime
        except OSError:
            pass
        while not stop_watch.is_set():
            try:
                if OPEN_UI_REQUEST.exists():
                    mtime = OPEN_UI_REQUEST.stat().st_mtime
                    if mtime > last_seen:
                        last_seen = mtime
                        _open_browser(url, reason="signaled")
                        try:
                            OPEN_UI_REQUEST.unlink(missing_ok=True)
                        except OSError:
                            pass
            except OSError:
                pass
            stop_watch.wait(0.5)

    def _startup_open() -> None:
        # Wait until tray message loop is up; avoids installer Finish-click hitting the icon.
        time.sleep(1.0)
        if stop_watch.is_set():
            return
        # One intentional open on first start only.
        _open_browser(url, reason="startup")

    threading.Thread(target=_watch_open_requests, name="ytarr-open-watch", daemon=True).start()
    threading.Thread(target=_startup_open, name="ytarr-open-ui", daemon=True).start()
    icon.run()
    stop_watch.set()
    server.should_exit = True
    thread.join(timeout=5)
    _log("exited")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        if not getattr(sys, "frozen", False) and sys.version_info < (3, 12):
            raise SystemExit("ytarr requires Python 3.12+")
        main()
    except SystemExit:
        raise
    except Exception:
        _log("fatal:\n" + traceback.format_exc())
        raise
