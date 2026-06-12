"""TranscriptionBuffer: accumulates transcription fragments and flushes on silence detection."""

from __future__ import annotations

import asyncio
from loguru import logger

log = logger


class TranscriptionBuffer:
    """Accumulates transcription fragments and flushes on silence detection.

    Flush triggers:
    - Silence detection: no new fragment for `silence_threshold` seconds + buffer > min
    - Buffer overflow: buffer exceeds `max_buffer_size` characters
    - Forced flush: explicit ``flush()`` call (e.g. on session close)
    """

    def __init__(
        self,
        max_buffer_size: int = 500,
        silence_threshold: float = 2.0,
        min_buffer_size: int = 20,
    ) -> None:
        self._fragments: list[str] = []
        self._raw_text: str = ""
        self._last_flush_time: float = 0.0
        self._last_fragment_time: float = 0.0
        self._max_buffer_size = max_buffer_size
        self._silence_threshold = silence_threshold
        self._min_buffer_size = min_buffer_size

    def add_fragment(self, text: str, now: float) -> tuple[str, bool]:
        """Add a transcription fragment.

        Returns:
            (accumulated_text, should_flush):
            - accumulated_text: current buffer content
            - should_flush: True if buffer should be sent to LLM
        """
        self._fragments.append(text)
        self._raw_text = " ".join(self._fragments)
        self._last_fragment_time = now

        should_flush = False
        if len(self._raw_text) >= self._max_buffer_size:
            should_flush = True
        elif (now - self._last_flush_time) >= self._silence_threshold:
            if len(self._raw_text) >= self._min_buffer_size:
                should_flush = True

        if should_flush:
            flush_text = self._raw_text
            self._fragments.clear()
            self._raw_text = ""
            self._last_flush_time = now
            return flush_text, should_flush

        return self._raw_text, should_flush

    def flush(self) -> str:
        """Clear buffer and return accumulated text."""
        text = self._raw_text
        self._fragments.clear()
        self._raw_text = ""
        return text

    def force_flush(self) -> str:
        """Flush remaining text regardless of size (used on session close)."""
        text = self._raw_text
        self._fragments.clear()
        self._raw_text = ""
        return text

    @property
    def raw_text(self) -> str:
        return self._raw_text

    @property
    def fragment_count(self) -> int:
        return len(self._fragments)
