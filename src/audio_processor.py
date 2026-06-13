"""AudioProcessor: handles chunking, feeding audio to recognizer, and parsing results.

Implements the BaseProcessor interface for plug-and-play interchangeability
with other processors (e.g. WhisperProcessor).
"""

from __future__ import annotations

import asyncio
import json
from loguru import logger

from vosk import KaldiRecognizer

from .base_processor import BaseProcessor

log = logger


class AudioProcessor(BaseProcessor):
    """Processes audio chunks through a Vosk recognizer and yields transcription events."""

    def __init__(
        self,
        recognizer: KaldiRecognizer,
        reset_interval: float = 45.0,
        partial_word_history: int = 5,
    ) -> None:
        self._recognizer = recognizer
        self._reset_interval = reset_interval
        self._partial_word_history = partial_word_history
        self._chunk_count = 0
        self._last_reset_time: float = 0.0
        self._last_final_text: str = ""
        self._last_partial_words: list[str] = []

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def needs_reset(self, now: float) -> bool:
        """Check if the recognizer should be reset based on the interval."""
        return now - self._last_reset_time >= self._reset_interval

    async def process_chunk(self, data: bytes) -> dict | None:
        """Process a single audio chunk. Returns a result dict or None.

        Delegates blocking Vosk calls to a thread pool to avoid blocking
        the event loop during high-throughput speech.
        """
        self._chunk_count += 1
        accepted = await asyncio.to_thread(self._recognizer.AcceptWaveform, data)

        if accepted:
            return await asyncio.to_thread(self._handle_accepted)
        return await asyncio.to_thread(self._handle_partial)

    def _reset_recognizer(self) -> None:
        """Replace the recognizer with a fresh instance."""
        # The actual recognizer replacement is handled by the caller
        # This method exists for API clarity; see SessionManager for replacement logic
        pass

    def _handle_accepted(self) -> dict | None:
        """Handle a chunk that was accepted (sentence boundary detected)."""
        result_str = self._recognizer.FinalResult()
        parsed = self._parse_result(result_str, is_final=True)
        if parsed is None:
            return None

        text = parsed.get("text", "").strip()
        if not text or text == self._last_final_text:
            return None

        self._last_final_text = text
        log.debug("FINAL [{}]", self._chunk_count)
        return {"type": "final", "text": text}

    def _handle_partial(self) -> dict | None:
        """Handle a chunk that was not accepted (partial/in-progress speech)."""
        partial_str = self._recognizer.PartialResult()
        parsed = self._parse_result(partial_str, is_final=False)
        if parsed is None:
            return None

        text = parsed.get("partial", "").strip()
        if not text:
            return None

        # Deduplicate partials by comparing last N words
        words = text.split()
        tail = words[-self._partial_word_history:] if len(words) >= self._partial_word_history else words
        if tail == self._last_partial_words:
            return None

        self._last_partial_words = tail
        return {"type": "partial", "text": text}

    def _parse_result(self, result_str: str, is_final: bool) -> dict | None:
        """Parse JSON result string, returning None on failure."""
        try:
            return json.loads(result_str)
        except json.JSONDecodeError:
            if is_final:
                log.warning("Bad {}Result JSON: {!r}", "Final" if is_final else "Partial", result_str[:200])
            return None

    def get_stats(self) -> dict:
        """Return processor statistics for logging."""
        return {
            "chunks": self._chunk_count,
            "last_final": self._last_final_text,
        }
