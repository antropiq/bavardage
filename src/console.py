"""Console mode: real-time French speech transcription directly in the terminal.

Uses the existing engine/processor abstractions from src/ — VoskEngine or
WhisperEngine paired with AudioProcessor or WhisperProcessor.

Usage:
    python -m src.console
    python -m src.console --engine whisper --whisper-model small
    python src/server.py --console
    python start.py --console
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from loguru import logger

from .audio_processor import AudioProcessor
from .vosk_engine import VoskEngine
from .whisper_engine import WhisperEngine, WhisperRecognizer
from .whisper_processor import WhisperProcessor


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Real-time speech transcription (console mode)",
    )
    parser.add_argument(
        "--engine",
        choices=["vosk", "whisper"],
        default="vosk",
        help="Transcription engine (default: vosk)",
    )
    parser.add_argument(
        "--vosk-model",
        default=None,
        help="Path to Vosk model directory (default: vosk-model-small-fr-0.22)",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        help=(
            "Whisper model size (tiny, base, small, medium, large) or "
            "local path (default: small)"
        ),
    )
    parser.add_argument(
        "--whisper-language",
        default="fr",
        help="Language code for Whisper (default: fr)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return parser


def _open_audio():
    """Open PyAudio stream at 16kHz mono, 4000 bytes per buffer."""
    import pyaudio

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=4000,
    )
    stream.start_stream()
    return p, stream


def _run_vosk_console(model_path: str | None) -> None:
    """Run transcription loop using Vosk engine."""
    engine = VoskEngine(model_path=model_path)
    engine.load()

    # Create a single recognizer directly (no pool needed for console)
    recognizer = engine._model
    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(recognizer, 16000)
    rec.SetWords(True)

    processor = AudioProcessor(rec)
    p, stream = _open_audio()

    print("Listening (Vosk, French)... Press Ctrl+C to stop.", file=sys.stderr)

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                break

            result = processor.process_chunk(data)
            if result is None:
                continue

            text = result.get("text", "").strip()
            if not text:
                continue

            if result["type"] == "final":
                print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{text}\x1b[0m")
                sys.stdout.flush()
            else:
                print(f"\r{text} ", end="", flush=True)

    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def _run_whisper_console(model_path: str, language: str) -> None:
    """Run transcription loop using Whisper engine."""
    engine = WhisperEngine(model_path=model_path, language=language)
    engine.load()

    recognizer = WhisperRecognizer(
        engine._model,
        language=language,
    )
    processor = WhisperProcessor(recognizer)
    p, stream = _open_audio()

    print(f"Listening (Whisper, {language})... Press Ctrl+C to stop.", file=sys.stderr)

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                break

            result = processor.process_chunk(data)
            if result is None:
                continue

            text = result.get("text", "").strip()
            if not text:
                continue

            if result["type"] == "final":
                print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{text}\x1b[0m")
                sys.stdout.flush()
            else:
                print(f"\r{text} ", end="", flush=True)

    except KeyboardInterrupt:
        # Flush remaining audio
        remaining = processor.flush_remaining()
        if remaining:
            print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{remaining}\x1b[0m")
            sys.stdout.flush()
        print("\nStopped.", file=sys.stderr)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    if args.engine == "vosk":
        _run_vosk_console(args.vosk_model)
    else:
        _run_whisper_console(args.whisper_model, args.whisper_language)


if __name__ == "__main__":
    main()
