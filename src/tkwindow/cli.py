"""CLI entry point for the tkwindow transcription application.

Handles argument parsing, logging setup, and application launch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from .window import TkWindow


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and launch the transcription window.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).
    """
    parser = argparse.ArgumentParser(description="Vosk transcription window")
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List available audio devices and exit",
    )
    parser.add_argument(
        "--vosk-model", default=None,
        help="Path to Vosk model (default: vosk-model-small-fr-0.22)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable DEBUG-level logging",
    )
    parser.add_argument(
        "--user-speaker", action="store_true",
        help="Capture system speaker output",
    )
    parser.add_argument(
        "--volume", type=float, default=1.0,
        help="Input volume multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--device", type=int, default=None,
        help="Audio device index",
    )
    parser.add_argument(
        "--transcription", nargs="?", const=str(Path.home() / "transcription.txt"), default=None,
        help="Write final transcription to a file (default: ~/transcription.txt)",
    )
    args = parser.parse_args(argv)

    if args.list_devices:
        _list_devices()
        return

    # Configure logging
    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    model_path = args.vosk_model or "vosk-model-small-fr-0.22"
    window = TkWindow(model_path, args.user_speaker, args.volume, args.device, args.transcription)
    window.run()


def _list_devices() -> None:
    """List available audio sources and exit."""
    from .devices import list_all_sources

    sources = list_all_sources()
    if sources:
        print("=== Available audio sources ===")
        for idx, (name, desc, src_type) in enumerate(sources):
            print(f"  {idx}: [{src_type.upper()}] {name} \u2014 {desc}")
    else:
        print("No audio sources found.")
