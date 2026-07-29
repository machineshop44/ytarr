"""Launch yt-dlp with OS certificate trust on Windows (Surfshark/VPN roots)."""
from __future__ import annotations

import sys


def main() -> None:
    if sys.platform.startswith("win"):
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:
            pass
    from yt_dlp import main as ytdlp_main

    ytdlp_main()


if __name__ == "__main__":
    main()
