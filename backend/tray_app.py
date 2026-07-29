"""ytarr system-tray launcher (no console window)."""
from __future__ import annotations

import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

# Resolve imports before other app imports
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

LOG_PATH = PROJECT_ROOT / "data" / "ytarr-tray.log"


def _log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
    except Exception:
        pass


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _make_icon():
    """Brand mark: green play circle (same as assets/ytarr.ico / favicon)."""
    from PIL import Image, ImageDraw

    for name in ("ytarr.png", "ytarr.ico"):
        path = PROJECT_ROOT / "assets" / name
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
    from app.config import get_config

    cfg = get_config()
    url = _ui_url()
    _log(f"start host={cfg.host} port={cfg.port} py={sys.version}")

    # pythonw has no stdout/stderr — uvicorn color logging crashes without this
    if sys.stdout is None:
        sys.stdout = open(LOG_PATH, "a", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = sys.stdout

    if _port_open("127.0.0.1", cfg.port):
        _log("already running — opening browser")
        webbrowser.open(url)
        return

    import pystray
    from pystray import MenuItem as Item
    import uvicorn

    server_config = uvicorn.Config(
        "app.main:app",
        host=cfg.host,
        port=cfg.port,
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

    _log("listening — starting tray icon")

    def open_ui(icon=None, item=None) -> None:  # noqa: ARG001
        webbrowser.open(url)

    def open_activity(icon=None, item=None) -> None:  # noqa: ARG001
        webbrowser.open(f"{url}/activity")

    def quit_app(icon, item=None) -> None:  # noqa: ARG001
        _log("quit requested")
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon(
        name="ytarr",
        icon=_make_icon(),
        title=f"ytarr — {url}",
        menu=pystray.Menu(
            Item("Open ytarr", open_ui, default=True),
            Item("Activity", open_activity),
            Item("Quit", quit_app),
        ),
    )

    webbrowser.open(url)
    icon.run()
    server.should_exit = True
    thread.join(timeout=5)
    _log("exited")


if __name__ == "__main__":
    try:
        if sys.version_info < (3, 12):
            raise SystemExit("ytarr requires Python 3.12+")
        main()
    except SystemExit:
        raise
    except Exception:
        _log("fatal:\n" + traceback.format_exc())
        raise
