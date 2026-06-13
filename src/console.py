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

from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.text import Text
from vosk import KaldiRecognizer, Model


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real-time speech transcription (Vosk)")
    parser.add_argument("--engine", choices=["vosk", "whisper"], default="vosk", help="Transcription engine (default: vosk)")
    parser.add_argument("--vosk-model", default=None, help="Path to Vosk model (default: vosk-model-small-fr-0.22)")
    parser.add_argument("--whisper-model", default="small", help="Whisper model size or local path (default: small)")
    parser.add_argument("--whisper-language", default="fr", help="Language code for Whisper (default: fr)")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG-level logging")
    parser.add_argument("--user-speaker", action="store_true", help="Capture system speaker output instead of microphone")
    parser.add_argument("--volume", type=float, default=1.0, help="Input volume multiplier (default: 1.0)")
    parser.add_argument("--device", type=int, default=None, help="Audio device index (skips interactive selection)")
    return parser


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
            delta = text[len(self._displayed):]
            if delta:
                self.final_lines.append(Text(delta, style="bold yellow"))
                self._displayed = text
        else:
            # Correction or reset — replace displayed text
            self.final_lines = [Text(text, style="bold yellow")]
            self._displayed = text
        self.live.update(self._render())

    def update_partial(self, text: str) -> None:
        self.partial_text = text
        self.live.update(self._render())

    def start(self) -> None:
        self.live.start()

    def stop(self) -> None:
        self.live.stop()


async def run_console(model_path=None, user_speaker=False, volume=1.0, device=None):
    if model_path is None:
        model_path = "vosk-model-small-fr-0.22"

    model = Model(model_path)
    rec = KaldiRecognizer(model, 16000)
    rec.SetWords(True)

    # Select source
    source_name = _select_source(user_speaker, device)
    if source_name is None:
        logger.error("No source selected, exiting.")
        return

    # Start parec subprocess (16kHz mono s16le)
    proc = subprocess.Popen(
        ["parec", "--device", source_name, "--format", "s16le", "--rate", "16000", "--channels", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    def _kill():
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    console = Console()
    display = SubtitleDisplay(console)
    display.start()

    try:
        print(f"Listening ({'monitor' if user_speaker else 'mic'})... Press Ctrl+C to stop.", file=sys.stderr)

        last_final = ""
        last_partial = ""
        chunk_count = 0

        while True:
            data = await asyncio.to_thread(proc.stdout.read, 1024)
            if len(data) == 0:
                break

            if volume > 1.0:
                data = _amplify(data, volume)

            chunk_count += 1
            accepted = rec.AcceptWaveform(data)

            if accepted:
                result_str = rec.FinalResult()
                result = json.loads(result_str)
                text = result.get("text", "").strip()
                if text and text != last_final:
                    display.commit_final(text)
                    last_final = text
                    last_partial = ""
            else:
                partial_str = rec.PartialResult()
                partial = json.loads(partial_str)
                partial_text = partial.get("partial", "").strip()
                if partial_text and partial_text != last_partial:
                    display.update_partial(partial_text)
                    last_partial = partial_text

    except KeyboardInterrupt:
        display.stop()
        console.print("\nStopped.")
    finally:
        _kill()


async def _run_vosk_console(args) -> None:
    """Run console transcription with Vosk engine."""
    model_path = args.vosk_model or "vosk-model-small-fr-0.22"
    await run_console(model_path, args.user_speaker, args.volume, args.device)


async def _run_whisper_console(args) -> None:
    """Run console transcription with Whisper engine."""
    from src.whisper_engine import WhisperEngine
    from src.transcription_buffer import TranscriptionBuffer
    from src.whisper_processor import WhisperProcessor

    engine = WhisperEngine(args.whisper_model, language=args.whisper_language, device="auto")
    engine.load()
    buffer = TranscriptionBuffer()
    processor = WhisperProcessor(engine, buffer)

    console = Console()
    console.print(f"[bold]Listening with Whisper ({args.whisper_language})... Press Ctrl+C to stop.[/bold]")

    try:
        while True:
            import pyaudio
            break
    except ImportError:
        console.print("[red]PyAudio not available for Whisper console mode.[/red]")
        return

    # Use PyAudio stream for Whisper console mode
    audio = pyaudio.PyAudio()
    try:
        stream = audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=4000,
        )
        last_final = ""
        last_partial = ""
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if volume > 1.0:
                data = _amplify(data, volume)
            result = processor.process_chunk(data)
            if result is not None:
                text = result.get("text", "")
                if result.get("type") == "final" and text and text != last_final:
                    display.commit_final(text)
                    last_final = text
                    last_partial = ""
                elif result.get("type") == "partial" and text and text != last_partial:
                    display.update_partial(text)
                    last_partial = text
    except KeyboardInterrupt:
        display.stop()
        console.print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        audio.terminate()


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    if args.engine == "vosk":
        try:
            asyncio.run(_run_vosk_console(args))
        except KeyboardInterrupt:
            pass
    elif args.engine == "whisper":
        try:
            asyncio.run(_run_whisper_console(args))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
