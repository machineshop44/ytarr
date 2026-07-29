from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import get_config
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
    get_config()
    init_db()
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
app.include_router(api_router)

# backend/app/main.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@app.get("/")
def root():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "name": "ytarr",
        "message": "API is running. Build the frontend (npm run build) or open /docs",
        "docs": "/docs",
    }


if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "openapi", "redoc")):
        raise HTTPException(status_code=404, detail="Not Found")
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend not built")


def create_app() -> FastAPI:
    return app
