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
BOOT_LOG = Path(os.environ.get("TEMP", PROJECT_ROOT / "data")) / "ytarr-boot.log"

# Cross-process + in-process cooldown (watchdogs can spawn us every ~1s)
_BROWSER_COOLDOWN_SEC = 30.0
_last_browser_open = 0.0
_browser_lock = threading.Lock()
_instance_mutex = None  # keep handle alive for process lifetime


def _boot_log(msg: str) -> None:
    """Always try to leave a breadcrumb (install data dir + %TEMP%)."""
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n"
    for path in (LOG_PATH, BOOT_LOG):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass


def _log(msg: str) -> None:
    _boot_log(msg)


def _attach_debug_console() -> None:
    """Alloc a console when launched with --debug so errors are visible."""
    if sys.platform != "win32" or "--debug" not in sys.argv:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        sys.stderr = sys.stdout
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")  # noqa: SIM115
        print("ytarr debug console attached", flush=True)
    except Exception:
        pass


def _notify_user(title: str, message: str) -> None:
    """Show a MessageBox so windowed builds aren't silent on failure."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # MB_ICONERROR
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
    try:
        bits.append(f"exe={sys.executable}")
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
    """Ask the already-running tray instance to open the UI."""
    try:
        OPEN_UI_REQUEST.parent.mkdir(parents=True, exist_ok=True)
        OPEN_UI_REQUEST.write_text(str(time.time()), encoding="utf-8")
        _log("signaled running instance to open UI")
    except OSError:
        _log("failed to write open-ui request:\n" + traceback.format_exc())


def _acquire_single_instance() -> bool:
    """Return True if this process created the mutex (advisory only — port is authoritative)."""
    global _instance_mutex
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Clear sticky last-error — a prior 183 can make a *new* mutex look taken.
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, "Local\\ytarr_tray_single_instance")
        if not handle:
            _log("CreateMutexW returned NULL; continuing")
            return True
        _instance_mutex = handle
        ERROR_ALREADY_EXISTS = 183
        err = int(kernel32.GetLastError())
        owns = err != ERROR_ALREADY_EXISTS
        _log(f"single-instance mutex owns={owns} last_error={err}")
        return owns
    except Exception:
        _log("single-instance mutex failed:\n" + traceback.format_exc())
        return True


def _wants_open_ui() -> bool:
    if "--open-ui" in sys.argv:
        return True
    return os.environ.get("YTARR_OPEN_UI", "").strip().lower() in {"1", "true", "yes"}


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
    # Safety net: never run the tray for frozen yt-dlp re-entry (even if early dispatch missed).
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "-m" and argv[1].replace("-", "_").startswith("yt_dlp"):
        _run_embedded_yt_dlp_if_requested()
        return

    _boot_log(f"boot {_caller_context()} root={PROJECT_ROOT}")

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
    open_ui = _wants_open_ui()
    _log(f"gate owns_lock={owns_lock} port_busy={port_busy} open_ui={open_ui}")

    # Port is the source of truth. Mutex alone must not block startup (hung tray
    # holding the mutex with no listener made the desktop icon / exe appear dead).
    if port_busy:
        _log("port already in use — another ytarr is live")
        if open_ui:
            _request_open_ui()
            # Direct open so a dead primary watch thread still doesn't strand the user
            _open_browser(url, reason="already-running-open-ui")
        return

    if not owns_lock:
        _log(
            "mutex held but port is free — treating as stale/hung instance; "
            "starting anyway (kill extra ytarr.exe in Task Manager if you see two trays)"
        )

    import pystray
    from pystray import MenuItem as Item
    import uvicorn

    # Frozen builds import the app object directly (string import breaks under PyInstaller)
    if getattr(sys, "frozen", False):
        from app.main import app as fastapi_app

        app_ref = fastapi_app
    else:
        app_ref = "app.main:app"

    # Honor config host (127.0.0.1 stays local-only; 0.0.0.0 for LAN)
    from app.config import normalize_bind_host

    raw_host = (cfg.host or "").strip()
    listen_host = normalize_bind_host(raw_host)
    listen_port = int(cfg.port)
    if listen_host != raw_host:
        _log(f"normalized bind host {raw_host!r} -> {listen_host!r}")
        cfg.host = listen_host
        try:
            from app.config import set_config

            set_config(cfg)
        except Exception:
            _log("could not persist normalized host:\n" + traceback.format_exc())
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

    for _ in range(100):
        if _port_open("127.0.0.1", cfg.port):
            break
        time.sleep(0.1)
    else:
        msg = (
            f"ytarr failed to listen on {listen_host}:{listen_port}.\n\n"
            f"Check the log:\n{LOG_PATH}\n\n"
            f"Also: {BOOT_LOG}"
        )
        _log("server failed to listen in time")
        _notify_user("ytarr failed to start", msg)
        return

    _log("listening - starting tray icon")

    def open_ui_item(icon=None, item=None) -> None:  # noqa: ARG001
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
        title=f"ytarr — {url}",
        menu=pystray.Menu(
            Item("Open ytarr", open_ui_item),
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
        time.sleep(1.0)
        if stop_watch.is_set():
            return
        _open_browser(url, reason="startup")

    threading.Thread(target=_watch_open_requests, name="ytarr-open-watch", daemon=True).start()
    threading.Thread(target=_startup_open, name="ytarr-open-ui", daemon=True).start()
    icon.run()
    stop_watch.set()
    server.should_exit = True
    thread.join(timeout=5)
    _log("exited")


_YTDLP_REENTRY = False


def _run_embedded_yt_dlp_if_requested() -> bool:
    """Frozen builds: ``ytarr.exe -m yt_dlp …`` re-enters this exe — run yt-dlp, not tray."""
    global _YTDLP_REENTRY
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "-m" and argv[1].replace("-", "_").startswith("yt_dlp"):
        sys.argv = [sys.argv[0], *argv[2:]]
    elif argv and argv[0] == "--yt-dlp":
        sys.argv = [sys.argv[0], *argv[1:]]
    elif argv and Path(argv[0]).name in {"ytdlp_launch.py", "yt_dlp"}:
        sys.argv = [sys.argv[0], *argv[1:]]
    else:
        return False
    _YTDLP_REENTRY = True
    if sys.platform.startswith("win"):
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:
            pass
    from yt_dlp import main as ytdlp_main

    raise SystemExit(ytdlp_main())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _run_embedded_yt_dlp_if_requested()
    _attach_debug_console()
    try:
        if not getattr(sys, "frozen", False) and sys.version_info < (3, 12):
            raise SystemExit("ytarr requires Python 3.12+")
        main()
    except SystemExit as exc:
        # yt-dlp tool exits must not pop "ytarr exited" dialogs
        if not _YTDLP_REENTRY and exc.code not in (0, None):
            _boot_log(f"SystemExit: {exc.code}")
            _notify_user(
                "ytarr exited",
                f"ytarr exited early ({exc.code}).\n\nSee:\n{LOG_PATH}\n{BOOT_LOG}",
            )
        raise
    except Exception:
        err = traceback.format_exc()
        _boot_log("fatal:\n" + err)
        print(err, file=sys.stderr)
        _notify_user(
            "ytarr crashed",
            f"ytarr failed to start.\n\nSee:\n{LOG_PATH}\n{BOOT_LOG}\n\n{err[-1500:]}",
        )
        if "--debug" in sys.argv:
            input("Press Enter to close…")
        raise
