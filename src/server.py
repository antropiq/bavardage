"""Real-time French speech transcription server using Vosk Kaldi (fully offline).

Entry point: starts the aiohttp server on port 8765 with WebSocket audio streaming.
Supports optional LLM post-processing via OpenAI-compatible API.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.server_app import ServerApp

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Speech transcription server")

    # Existing arguments
    parser.add_argument(
        "--engine",
        choices=["vosk", "whisper"],
        default="vosk",
        help="Transcription engine (default: vosk)",
    )

    # New LLM arguments
    parser.add_argument(
        "--llm-url",
        default=None,
        help=(
            "LLM API URL (e.g., http://192.168.1.100:8080). "
            "If not set, LLM post-processing is disabled."
        ),
    )
    parser.add_argument(
        "--llm-key",
        default=None,
        help="LLM API key (if required by the server)",
    )
    parser.add_argument(
        "--llm-model",
        default="llama3",
        help="LLM model name (default: llama3)",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=5.0,
        help="LLM API timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--llm-buffer-max",
        type=int,
        default=500,
        help="Max buffer size in characters before forced flush (default: 500)",
    )
    parser.add_argument(
        "--llm-silence-threshold",
        type=float,
        default=2.0,
        help="Silence threshold in seconds to trigger flush (default: 2.0)",
    )
    parser.add_argument(
        "--llm-buffer-min",
        type=int,
        default=20,
        help="Min buffer size in characters to avoid tiny flushes (default: 20)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = ServerApp.from_args(args)
    app.run()


if __name__ == "__main__":
    main()
