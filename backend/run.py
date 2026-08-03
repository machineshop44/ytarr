"""Run ytarr API server."""
from __future__ import annotations

import uvicorn

from app.config import get_config, record_listen_bind, config_file_path


def main() -> None:
    cfg = get_config()
    host = (cfg.host or "").strip() or "0.0.0.0"
    port = int(cfg.port)
    record_listen_bind(host, port)
    print(f"ytarr listening on {host}:{port} (config {config_file_path()})")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
