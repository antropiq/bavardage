"""Real-time French speech transcription server using Vosk Kaldi (fully offline).

Entry point: starts the aiohttp server on port 8765 with WebSocket audio streaming.
"""

from __future__ import annotations

import logging
import sys

from src.server_app import ServerApp

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def main() -> None:
    app = ServerApp()
    app.run()


if __name__ == "__main__":
    main()
