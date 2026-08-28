from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .auth import ApiKeyMiddleware
from .config import ensure_auth_credentials, get_config
from .db import init_db
from .paths import project_root, resource_path
from .services.applog import setup_app_logging
from .services.scheduler import start_scheduler, stop_scheduler
from .version import app_version


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Trust Windows/macOS system CAs (VPN roots like Surfshark) without disabling verify
    try:
        import sys

        if sys.platform.startswith("win"):
            import truststore

            truststore.inject_into_ssl()
    except Exception:
        pass
    setup_app_logging()
    ensure_auth_credentials(get_config())
    init_db()
    # Failed videos are already in the DB / Activity — don't re-spam the log on every boot.
    try:
        from .services import downloader

        downloader.recover_interrupted_downloads()
    except Exception:
        pass
    # Collapse existing playlist posters under their channel (once, in background).
    try:
        import threading

        from .db import SessionLocal
        from .services import monitor

        def _link_playlists() -> None:
            import time

            s = SessionLocal()
            try:
                n = monitor.link_orphan_playlists_fast(s)
                if n:
                    from .services import applog

                    applog.log_info(
                        f"Nested {n} playlist(s) under their channel in the library",
                        source="startup",
                    )
            except Exception:
                s.rollback()
            finally:
                s.close()
            # YouTube /playlists scrape is slow — don't block boot; cap channels.
            time.sleep(45)
            s2 = SessionLocal()
            try:
                n2 = monitor.link_orphan_playlists(
                    s2, scrape=True, max_channels=5, skip_fast=True
                )
                if n2:
                    from .services import applog

                    applog.log_info(
                        f"Nested {n2} more playlist(s) after YouTube playlist lookup",
                        source="startup",
                    )
            except Exception:
                s2.rollback()
            finally:
                s2.close()

        threading.Thread(target=_link_playlists, name="ytarr-link-playlists", daemon=True).start()
    except Exception:
        pass
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="ytarr", version=app_version(), lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Auth after CORS so preflight succeeds; middleware stack is LIFO
app.add_middleware(ApiKeyMiddleware)
app.include_router(api_router)

# Writable install root (folder with ytarr.exe) / repo root in dev
PROJECT_ROOT = project_root()
FRONTEND_DIST = resource_path("frontend", "dist")


def _inject_bootstrap(html: str, request: Request | None = None) -> str:
    """Embed bootstrap for the SPA. API key only when Forms session (or no Forms)."""
    from . import auth as auth_mod

    cfg = ensure_auth_credentials(get_config())
    authenticated = False
    if auth_mod.forms_enabled(cfg):
        authenticated = bool(request and auth_mod.session_username(request))
    else:
        authenticated = True
    bootstrap = {
        "apiKey": cfg.api_key if authenticated else "",
        "apiAuthRequired": bool(cfg.api_auth_required),
        "authenticationMethod": cfg.authentication_method or "forms",
        "formsRequired": auth_mod.forms_enabled(cfg),
        "authenticated": authenticated,
        "username": cfg.username if authenticated else "",
        "port": cfg.port,
    }
    script = "<script>window.__YTARR__=" + json.dumps(bootstrap) + ";</script>"
    if "</head>" in html:
        return html.replace("</head>", script + "</head>", 1)
    return script + html


def _spa_index(request: Request | None = None) -> HTMLResponse | dict:
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        return HTMLResponse(_inject_bootstrap(html, request))
    return {
        "name": "ytarr",
        "message": "API is running. Build the frontend (npm run build) or open /docs",
        "docs": "/docs",
        "hint": "Set host to 0.0.0.0 and use Settings → General API key for mobile hubs",
    }


@app.get("/")
def root(request: Request):
    return _spa_index(request)


if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str, request: Request):
    if full_path.startswith(("api/", "docs", "openapi", "redoc")):
        raise HTTPException(status_code=404, detail="Not Found")
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        return HTMLResponse(_inject_bootstrap(html, request))
    raise HTTPException(status_code=404, detail="Frontend not built")


def create_app() -> FastAPI:
    return app
