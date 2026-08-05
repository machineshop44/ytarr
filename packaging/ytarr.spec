# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ytarr (portable Windows tray exe)."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

SPECDIR = Path(SPEC).resolve().parent
ROOT = SPECDIR.parent

datas = [
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "config.example.yaml"), "."),
    (str(ROOT / "VERSION"), "."),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "app.main",
    "app.api",
    "app.auth",
    "app.config",
    "app.db",
    "app.paths",
    "app.schemas",
    "app.models",
    "app.services",
    "app.services.monitor",
    "app.services.downloader",
    "app.services.ytdlp",
    "app.services.rename",
    "app.services.discover",
    "app.services.musicbrainz",
    "app.services.quality",
    "app.services.scheduler",
    "app.services.ytdlp_update",
    "app.services.applog",
    "app.version",
    "truststore",
    "certifi",
]

for pkg in ("yt_dlp", "fastapi", "starlette", "pydantic", "anyio", "sqlalchemy"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

binaries = []
tmp_ret = collect_all("yt_dlp")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

icon = ROOT / "assets" / "ytarr.ico"

a = Analysis(
    [str(ROOT / "backend" / "tray_app.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ytarr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ytarr",
)
