"""Console mode: real-time French speech transcription (Vosk only).

Designed for subtitle display: partials update live, finals commit cleanly.
Uses parec for PipeWire/PulseAudio monitor source capture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import subprocess
import sys

from typing import Any

from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.text import Text
from src.vosk_engine import VoskEngine
from src.whisper_engine import WhisperEngine
from src.audio_processor import AudioProcessor
from src.whisper_processor import WhisperProcessor
from src.tkwindow.audio import create_audio_capture


def _list_monitor_sources() -> list[tuple[str, str]]:
    """List PipeWire/PulseAudio monitor sources."""
    try:
        out = subprocess.check_output(["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    sources = []
    current = {}
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("Source #"):
            if current:
                sources.append(current)
            current = {}
        if line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            current["desc"] = line.split(":", 1)[1].strip()
    if current:
        sources.append(current)

    return [(s["name"], s.get("desc", "")) for s in sources if "monitor" in s.get("name", "").lower()]


def _list_microphone_sources() -> list[tuple[str, str]]:
    """List PipeWire/PulseAudio microphone/input sources."""
    try:
        out = subprocess.check_output(["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    sources = []
    current = {}
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("Source #"):
            if current and "monitor" not in current.get("name", "").lower():
                sources.append(current)
            current = {}
        if line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            current["desc"] = line.split(":", 1)[1].strip()
    if current and "monitor" not in current.get("name", "").lower():
        sources.append(current)

    return [(s["name"], s.get("desc", "")) for s in sources]


def _select_source(user_speaker: bool, device_idx: int | None = None) -> str | None:
    """Select an audio source. Returns the source name for parec."""
    sources = _list_monitor_sources() if user_speaker else _list_microphone_sources()
    label = "Monitor sources (captures from output devices)" if user_speaker else "Microphone/input sources"

    if not sources:
        logger.error("No audio sources found.")
        return None

    print(f"{label}:", file=sys.stderr)
    for i, (name, desc) in enumerate(sources):
        print(f"  [{i}] {name}", file=sys.stderr)
        if desc:
            print(f"      {desc}", file=sys.stderr)
    print(file=sys.stderr)

    if device_idx is not None:
        if 0 <= device_idx < len(sources):
            name, desc = sources[device_idx]
            print(f"Using device {device_idx}: {name}", file=sys.stderr)
            return name
        logger.error(f"Device index {device_idx} out of range (0-{len(sources)-1}).")
        return None

    print("Select source index:", file=sys.stderr)
    try:
        choice = input("> ").strip()
    except EOFError:
        choice = ""

    try:
        chosen = int(choice)
        if 0 <= chosen < len(sources):
            return sources[chosen][0]
    except ValueError:
        pass

    logger.error(f"Invalid source index: {choice}")
    return None


def _amplify(data: bytes, volume: float) -> bytes:
    """Amplify raw int16 PCM samples."""
    import numpy as np
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) * volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()


# --- Subtitle rendering with Rich Live ---


class SubtitleDisplay:
    """Manages partial/final subtitle display using Rich Live."""

    def __init__(self, console: Console) -> None:
        self.console = console
        self.final_lines: list[Text] = []
        self.partial_text: str = ""
        self._displayed: str = ""
        self.live = Live("", console=console, refresh_per_second=10, screen=False)

    def _render(self) -> Text:
        parts: list[Text] = []
        for line in self.final_lines:
            parts.append(line)
            parts.append(Text("\n"))
        if self.partial_text:
            parts.append(Text(self.partial_text, style="italic dim_white"))
        result = Text.assemble(*parts)
        return result

    def commit_final(self, text: str) -> None:
        self.partial_text = ""
        if not text:
            self.live.update(self._render())
            return
        # Vosk FinalResult() is cumulative — only append the delta
        if text.startswith(self._displayed):
            # It's a continuation of the current line
            if self.final_lines:
                # Update the last line with the new text (which includes the prefix)
                self.final_lines[-1] = Text(text, style="bold yellow")
            else:
                self.final_lines.append(Text(text, style="bold yellow"))
            self._displayed = text
        else:
            # Correction or new sentence — append as a new line to preserve history
            self.final_lines.append(Text(text, style="bold yellow"))
            self._displayed = text
        self.live.update(self._render())

    def update_partial(self, text: str) -> None:
        self.partial_text = text
        self.live.update(self._render())

    def start(self) -> None:
        self.live.start()

    def stop(self) -> None:
        self.live.stop()


async def _run_transcription(engine: Any, processor: Any, capture: Any, display: SubtitleDisplay, volume: float) -> None:
    try:
        print(f"Listening... Press Ctrl+C to stop.", file=sys.stderr)
        while True:
            data = await asyncio.to_thread(capture.read, 4000)
            if not data:
                break

            if volume > 1.0:
                data = _amplify(data, volume)

            result = await processor.process_chunk(data)
            if result:
                text = result.get("text", "").strip()
                if result.get("type") == "final":
                    display.commit_final(text)
                elif result.get("type") == "partial":
                    display.update_partial(text)
    except asyncio.CancelledError:
        display.stop()
        print("\nStopped.", file=sys.stderr)
        raise
    except KeyboardInterrupt:
        display.stop()
        print("\nStopped.", file=sys.stderr)


async def _run_vosk_console(args) -> None:
    model_path = args.vosk_model or "vosk-model-small-fr-0.22"
    engine = VoskEngine(model_path)
    recognizer = await engine.create_recognizer()
    processor = AudioProcessor(recognizer)
    
    source_name = _select_source(args.user_speaker, args.device)
    if source_name is None:
        logger.error("No source selected, exiting.")
        return

    capture = create_audio_capture(source_name)
    display = SubtitleDisplay(Console())
    display.start()
    
    try:
        await _run_transcription(engine, processor, capture, display, args.volume)
    finally:
        display.stop()
        capture.close()


async def _run_whisper_console(args) -> None:
    engine = WhisperEngine(args.whisper_model, language=args.whisper_language, device=args.whisper_device)
    engine.load()
    recognizer = await engine.create_recognizer()
    processor = WhisperProcessor(recognizer)
    
    source_name = _select_source(args.user_speaker, args.device)
    if source_name is None:
        logger.error("No source selected, exiting.")
        return

    capture = create_audio_capture(source_name)
    display = SubtitleDisplay(Console())
    display.start()
    
    try:
        await _run_transcription(engine, processor, capture, display, args.volume)
    finally:
        display.stop()
        capture.close()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for standalone console mode."""
    parser = argparse.ArgumentParser(description="Real-time speech transcription (Vosk or Whisper)")
    parser.add_argument("--engine", choices=["vosk", "whisper"], default="vosk", help="Transcription engine (default: vosk)")
    parser.add_argument("--vosk-model", default=None, help="Path to Vosk model (default: vosk-model-small-fr-0.22)")
    parser.add_argument("--whisper-model", default="small", help="Whisper model size or local path (default: small)")
    parser.add_argument("--whisper-language", default="fr", help="Language code for Whisper (default: fr)")
    parser.add_argument("--whisper-device", default="auto", help="Whisper device (default: auto)")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG-level logging")
    parser.add_argument("--user-speaker", action="store_true", help="Capture system speaker output instead of microphone")
    parser.add_argument("--volume", type=float, default=1.0, help="Input volume multiplier (default: 1.0)")
    parser.add_argument("--device", type=int, default=None, help="Audio device index (skips interactive selection)")
    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point for standalone console mode: python -m src.console."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    # Build a ParsedArgs-compatible namespace
    console_args = argparse.Namespace(
        engine=args.engine,
        vosk_model=args.vosk_model,
        whisper_model=args.whisper_model,
        whisper_language=args.whisper_language,
        whisper_device=args.whisper_device,
        user_speaker=args.user_speaker,
        volume=args.volume,
        device=args.device,
    )

    if args.engine == "vosk":
        try:
            asyncio.run(_run_vosk_console(console_args))
        except KeyboardInterrupt:
            pass
    elif args.engine == "whisper":
        try:
            asyncio.run(_run_whisper_console(console_args))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()



