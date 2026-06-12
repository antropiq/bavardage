"""WhisperProcessor: handles chunking, feeding audio to Whisper recognizer,
and parsing results.

Implements the BaseProcessor interface for plug-and-play interchangeability
with other processors (e.g. AudioProcessor).
"""

from __future__ import annotations

from loguru import logger

from .base_processor import BaseProcessor
from .whisper_engine import WhisperRecognizer

log = logger


class WhisperProcessor(BaseProcessor):
    """Processes audio chunks through a Whisper recognizer and yields transcription events."""

    def __init__(
        self,
        recognizer: WhisperRecognizer,
        reset_interval: float = 45.0,
    ) -> None:
        self._recognizer = recognizer
        self._reset_interval = reset_interval
        self._chunk_count = 0
        self._last_reset_time: float = 0.0
        self._last_final_text: str = ""

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def needs_reset(self, now: float) -> bool:
        """Check if the recognizer should be reset based on the interval."""
        return now - self._last_reset_time >= self._reset_interval

    def process_chunk(self, data: bytes) -> dict | None:
        """Process a single audio chunk. Returns a result dict or None.

        Delegates to the WhisperRecognizer which accumulates audio and
        transcribes when enough data is available.
        """
        self._chunk_count += 1
        result = self._recognizer.process_chunk(data)

        if result and result["type"] == "final":
            self._last_final_text = result["text"]
            log.debug("WHISPER FINAL [{}]: {}", self._chunk_count, self._last_final_text)

        return result

    def flush_remaining(self) -> str | None:
        """Flush any remaining buffered audio (called on session close/reset)."""
        text = self._recognizer.flush()
        if text:
            self._last_final_text = text
        return text

    def get_stats(self) -> dict:
        """Return processor statistics for logging."""
        return {
            "chunks": self._chunk_count,
            "last_final": self._last_final_text,
        }
