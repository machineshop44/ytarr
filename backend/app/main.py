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
from .services.scheduler import start_scheduler, stop_scheduler


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
    ensure_auth_credentials(get_config())
    init_db()
    try:
        from .services import downloader

        downloader.recover_interrupted_downloads()
    except Exception:
        pass
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="ytarr", version="0.1.0", lifespan=lifespan)
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

# backend/app/main.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


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
