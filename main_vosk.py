"""Real-time French speech transcription (terminal mode).

Supports both Vosk and Whisper engines via --engine flag.
Vosk: fully offline, gives partial results in real-time.
Whisper: uses faster-whisper (CTranslate2), better accuracy, needs model download.
"""

import argparse
import json
import sys

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description="Speech transcription (terminal)")
    parser.add_argument(
        "--engine",
        choices=["vosk", "whisper"],
        default="vosk",
        help="Transcription engine (default: vosk)",
    )
    parser.add_argument(
        "--vosk-model",
        default="vosk-model-small-fr-0.22",
        help="Path to Vosk model directory (default: vosk-model-small-fr-0.22)",
    )
    parser.add_argument(
        "--whisper-model",
        default="small",
        help=(
            "Whisper model size (tiny, base, small, medium, large) or "
            "local path to a downloaded model directory. "
            "Models from HuggingFace: Systran/faster-whisper-small, etc. "
            "(default: small)"
        ),
    )
    parser.add_argument(
        "--whisper-language",
        default="fr",
        help="Language code for Whisper (default: fr)",
    )
    args = parser.parse_args()

    if args.engine == "vosk":
        _run_vosk(args.vosk_model)
    else:
        _run_whisper(args.whisper_model, args.whisper_language)


def _run_vosk(model_path: str) -> None:
    """Run transcription using Vosk engine."""
    from vosk import Model, KaldiRecognizer
    import pyaudio

    try:
        model = Model(model_path)
    except Exception as e:
        print(f"Error loading Vosk model: {e}", file=sys.stderr)
        sys.exit(1)

    recognizer = KaldiRecognizer(model, 16000)

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=4000,
    )
    stream.start_stream()

    print("Listening (Vosk, French)... Press Ctrl+C to stop.", file=sys.stderr)

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                break

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.FinalResult())
                text = result.get("text", "").strip()
                if text:
                    print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{text}\x1b[0m")
                    sys.stdout.flush()
            else:
                partial = recognizer.PartialResult()
                if partial and "partial" in partial:
                    partial_text = json.loads(partial).get("partial", "").strip()
                    if partial_text:
                        print(f"\r{partial_text} ", end="", flush=True)

    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


def _run_whisper(model_path: str, language: str = "fr") -> None:
    """Run transcription using Whisper engine (faster-whisper)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "faster-whisper package not installed. Install it with: pip install faster-whisper",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        model = WhisperModel(model_path, device="cpu", compute_type="int8")
    except Exception as e:
        print(f"Error loading Whisper model: {e}", file=sys.stderr)
        sys.exit(1)

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

    print(f"Listening (Whisper, {language})... Press Ctrl+C to stop.", file=sys.stderr)

    audio_buffer: list[np.ndarray] = []
    total_samples = 0
    sample_rate = 16000

    try:
        while True:
            data = stream.read(4000, exception_on_overflow=False)
            if len(data) == 0:
                break

            # Convert int16 PCM to float32 normalized
            samples = (
                np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            )
            audio_buffer.append(samples)
            total_samples += len(samples)

            # Transcribe when we have at least 1 second of audio
            if total_samples >= sample_rate:
                audio = np.concatenate(audio_buffer)
                audio_buffer = []
                total_samples = 0

                try:
                    segments, info = model.transcribe(
                        audio,
                        language=language or None,
                        beam_size=1,
                        vad_filter=False,
                    )

                    texts = []
                    for seg in segments:
                        text = seg.text.strip()
                        if text:
                            texts.append(text)

                    if texts:
                        full_text = " ".join(texts)
                        print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{full_text}\x1b[0m")
                        sys.stdout.flush()

                except Exception as exc:
                    print(f"\nWhisper error: {exc}", file=sys.stderr)
                    # Put audio back in buffer for retry
                    audio_buffer.append(audio)
                    total_samples = len(audio)

    except KeyboardInterrupt:
        # Flush remaining audio
        if audio_buffer:
            audio = np.concatenate(audio_buffer)
            try:
                segments, _ = model.transcribe(
                    audio,
                    language=language or None,
                    beam_size=1,
                    vad_filter=False,
                )
                texts = []
                for seg in segments:
                    text = seg.text.strip()
                    if text:
                        texts.append(text)
                if texts:
                    print(f"\r{' ' * 80}\r\x1b[1m\x1b[93m{' '.join(texts)}\x1b[0m")
                    sys.stdout.flush()
            except Exception:
                pass
        print("\nStopped.", file=sys.stderr)
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()


if __name__ == "__main__":
    main()
