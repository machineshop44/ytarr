"""Run ytarr API server."""
from __future__ import annotations

import uvicorn

from app.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
