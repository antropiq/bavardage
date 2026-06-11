"""Real-time French speech transcription server.

Entry point: starts the aiohttp server on port 8765 with WebSocket audio streaming.
Supports multiple transcription engines (Vosk, Whisper) and optional LLM post-processing.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.server_app import ServerApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Speech transcription server")

    # Engine selection
    parser.add_argument(
        "--engine",
        choices=["vosk", "whisper"],
        default="vosk",
        help="Transcription engine (default: vosk)",
    )

    # Whisper-specific arguments
    parser.add_argument(
        "--whisper-model",
        default="small",
        help=(
            "Whisper model size (tiny, base, small, medium, large) or "
            "local path to a downloaded model directory. "
            "Models from HuggingFace: Systran/faster-whisper-small, etc. "
            "(default: small — better accuracy for French)"
        ),
    )
    parser.add_argument(
        "--whisper-language",
        default="fr",
        help="Language code for Whisper transcription (default: fr)",
    )
    parser.add_argument(
        "--whisper-device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Whisper device (default: auto — detects CUDA if available)",
    )

    # LLM arguments
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
        default=15.0,
        help="LLM API timeout in seconds (default: 15.0)",
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

    # SSL arguments
    parser.add_argument(
        "--ssl",
        action="store_true",
        default=False,
        help="Enable HTTPS with a self-signed certificate (required for LAN microphone access)",
    )
    parser.add_argument(
        "--ssl-certfile",
        default=None,
        help="Path to SSL certificate file (default: auto-generates in .ssl/ directory)",
    )
    parser.add_argument(
        "--ssl-keyfile",
        default=None,
        help="Path to SSL private key file (default: auto-generates in .ssl/ directory)",
    )

    # Logging
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(logging.DEBUG if args.debug else logging.INFO)
    app = ServerApp.from_args(args)
    app.run()


if __name__ == "__main__":
    main()
