"""WhisperEngine: Whisper-based transcription engine using faster-whisper (CTranslate2).

Implements the BaseEngine interface for plug-and-play interchangeability
with other transcription engines (e.g. VoskEngine).

Requires: faster-whisper (already installed in this project)
Models: downloaded from HuggingFace or placed locally.
Download models from: https://huggingface.co/Systran (e.g. Systran/faster-whisper-small)

Usage:
    python start.py --engine whisper --whisper-model Systran/faster-whisper-small
    python start.py --engine whisper --whisper-model ./models/faster-whisper-small
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from .base_engine import BaseEngine

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


class WhisperRecognizer:
    """Wraps a faster-whisper model for batched transcription.

    Uses silence-based triggering: audio accumulates while the user speaks,
    and is transcribed after 2 seconds of silence (sentence boundary).
    The buffer is cleared after each transcription so subsequent segments
    are processed independently.
    """

    # Silence threshold (seconds) — when silence exceeds this, transcribe
    SILENCE_THRESHOLD_SECONDS = 2.0
    # Min audio (seconds) before we consider a result valid
    MIN_AUDIO_SECONDS = 0.5
    # Max buffer size (seconds) — force flush to avoid unbounded growth
    MAX_BUFFER_SECONDS = 30.0

    def __init__(
        self,
        model: Any,
        sample_rate: int = 16000,
        language: str = "fr",
    ) -> None:
        self._model = model
        self._sample_rate = sample_rate
        self._language = language
        self._audio_buffer: list[np.ndarray] = []  # type: ignore[name-defined]
        self._total_samples = 0
        self._last_transcript: str = ""
        # Silence tracking
        self._silence_start: float | None = None
        self._is_speaking = True
        self._last_chunk_time: float = 0.0
        self._last_final_text: str = ""

    def _is_silent(self, samples: np.ndarray) -> bool:
        """Check if audio samples are silent (low RMS energy)."""
        if len(samples) == 0:
            return True
        rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))
        # Threshold: silence when RMS < 0.01 (roughly -40 dB)
        return rms < 0.01

    def process_chunk(self, data: bytes) -> dict | None:
        """Process an audio chunk.

        Audio accumulates while the user speaks. When silence exceeds
        SILENCE_THRESHOLD_SECONDS, the accumulated buffer is transcribed
        and cleared. Short pauses within a sentence don't trigger transcription.
        """
        now = time.time()
        self._last_chunk_time = now

        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        silent = self._is_silent(samples)

        if not silent:
            # User is speaking — reset silence tracking
            if self._silence_start is not None:
                # Transition from silence to speaking — start new segment
                self._silence_start = None
            self._is_speaking = True
        else:
            # User is silent
            if self._is_speaking:
                # Just stopped speaking — mark silence start
                self._is_speaking = False
                self._silence_start = now

        self._audio_buffer.append(samples)
        self._total_samples += len(samples)

        # Check if silence threshold exceeded — time to transcribe
        if self._silence_start is not None and not self._is_speaking:
            silence_duration = now - self._silence_start
            if silence_duration >= self.SILENCE_THRESHOLD_SECONDS:
                return self._transcribe()

        # Force flush if buffer gets too large
        if self._total_samples >= self.MAX_BUFFER_SECONDS * self._sample_rate:
            return self._transcribe()

        return None

    def _transcribe(self) -> dict | None:
        """Transcribe the current audio buffer and reset state."""
        if self._total_samples < self.MIN_AUDIO_SECONDS * self._sample_rate:
            # Not enough audio — just reset and return None
            self._audio_buffer = []
            self._total_samples = 0
            self._silence_start = None
            return None

        audio = np.concatenate(self._audio_buffer)
        self._audio_buffer = []
        self._total_samples = 0
        self._silence_start = None

        try:
            segments, info = self._model.transcribe(
                audio,
                language=self._language or None,
                beam_size=2,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 200,
                    "threshold": 0.6,
                },
                initial_prompt=self._initial_prompt(),
            )

            texts = [seg.text.strip() for seg in segments if seg.text.strip()]
            if texts:
                full_text = " ".join(texts)
                if full_text != self._last_transcript:
                    self._last_transcript = full_text
                    self._last_final_text = full_text
                    return {"type": "final", "text": full_text}

        except Exception as exc:
            log.warning("Whisper transcription failed: %s", exc)

        return None

    def _initial_prompt(self) -> str:
        """Return a language-specific initial prompt for better accuracy."""
        prompts = {
            "fr": "Transcription en français.",
            "en": "Transcription in English.",
            "es": "Transcripción en español.",
            "de": "Transkription auf Deutsch.",
            "it": "Trascrizione in italiano.",
            "pt": "Transcrição em português.",
            "zh": "中文转录。",
            "ja": "日本語のトランスクリプション。",
            "ru": "Транскрипция на русском.",
            "ar": "النقل باللغة العربية.",
        }
        lang = self._language.lower()
        return prompts.get(lang, f"This is a transcription in {lang}. Use correct punctuation and grammar.")

    def flush(self) -> str | None:
        """Transcribe any remaining buffered audio."""
        if not self._audio_buffer:
            return None

        audio = np.concatenate(self._audio_buffer)
        self._audio_buffer = []
        self._total_samples = 0
        self._silence_start = None

        try:
            segments, info = self._model.transcribe(
                audio,
                language=self._language or None,
                beam_size=2,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": 200,
                    "threshold": 0.6,
                },
                initial_prompt=self._initial_prompt(),
            )

            texts = [s.text.strip() for s in segments if s.text.strip()]
            if texts:
                full_text = " ".join(texts)
                if full_text != self._last_transcript:
                    self._last_transcript = full_text
                    return full_text

        except Exception as exc:
            log.warning("Whisper flush transcription failed: %s", exc)

        return None

    def reset(self) -> None:
        """Reset the buffer and state."""
        self._audio_buffer = []
        self._total_samples = 0
        self._last_transcript = ""
        self._silence_start = None
        self._is_speaking = True
        self._last_final_text = ""

    @property
    def total_samples(self) -> int:
        return self._total_samples


class WhisperEngine(BaseEngine):
    """Encapsulates the faster-whisper ML library: model loading and recognizer lifecycle.

    Implements the BaseEngine interface.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        model_size: str = "small",
        language: str = "fr",
        device: str = "auto",
    ) -> None:
        self._model_path = str(model_path) if model_path else None
        self._model_size = model_size
        self._language = language
        self._device = device
        self._loaded = False
        self._model: Any = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Load the faster-whisper model eagerly. Blocks until ready."""
        if self._loaded:
            return

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            log.error(
                "faster-whisper package not installed. "
                "Install it with: pip install faster-whisper"
            )
            raise

        model_source = self._model_path or self._model_size
        log.debug(
            "Loading faster-whisper model from %s (this may take a moment)...",
            model_source,
        )

        # Resolve device: "auto" detects CUDA, "cuda" forces GPU, "cpu" forces CPU
        if self._device == "auto":
            try:
                import torch
                use_cuda = torch.cuda.is_available()
            except ImportError:
                use_cuda = False
            device = "cuda" if use_cuda else "cpu"
        else:
            device = self._device

        # Compute type: float16 for GPU (faster, good quality), int8 for CPU
        compute_type = "float16" if device == "cuda" else "int8"

        log.debug(
            "Loading faster-whisper model from %s on %s (%s)...",
            model_source,
            device,
            compute_type,
        )

        self._model = WhisperModel(
            model_source,
            device=device,
            compute_type=compute_type,
        )
        self._loaded = True
        log.debug("faster-whisper model loaded.")

    async def create_recognizer(self) -> WhisperRecognizer:
        """Create a new WhisperRecognizer with the loaded model."""
        if not self._loaded:
            self.load()
        if self._model is None:
            self.load()

        recognizer = WhisperRecognizer(
            model=self._model,
            language=self._language,
        )
        log.debug("Created new WhisperRecognizer")
        return recognizer

    async def return_recognizer(self, recognizer: WhisperRecognizer) -> None:
        """Reset a recognizer for reuse."""
        if recognizer:
            recognizer.reset()

    def parse_final_result(self, result_str: str) -> dict | None:
        """Parse and validate a final result JSON string."""
        try:
            result = json.loads(result_str) if isinstance(result_str, str) else result_str
        except (json.JSONDecodeError, TypeError):
            return None

        if isinstance(result, dict):
            text = result.get("text", "").strip()
            if not text:
                return None
            return result

        return None

    def parse_partial_result(self, partial_str: str) -> dict | None:
        """Parse and validate a partial result JSON string."""
        try:
            partial = json.loads(partial_str) if isinstance(partial_str, str) else partial_str
        except (json.JSONDecodeError, TypeError):
            return None

        if isinstance(partial, dict):
            return partial

        return None

    def get_health_status(self) -> dict:
        """Return health status for the /health endpoint."""
        if self._loaded:
            return {"status": "ready"}
        return {"status": "loading"}
