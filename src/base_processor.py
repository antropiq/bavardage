"""BaseProcessor: abstract interface for audio processing engines.

All processors (AudioProcessor, WhisperProcessor, etc.) must implement this
interface to be interchangeable in the session pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseProcessor(ABC):
    """Abstract base class defining the audio processor interface.

    Public contract:
    - ``process_chunk(data)``: Feed an audio chunk, return a result dict or None.
    - ``needs_reset(now)``: Check if the processor should be reset.
    - ``get_stats()``: Return processor statistics.
    """

    @property
    @abstractmethod
    def chunk_count(self) -> int:
        """Number of chunks processed so far."""
        ...

    @abstractmethod
    def process_chunk(self, data: bytes) -> dict | None:
        """Process a single audio chunk. Returns a result dict or None.

        Result dict format: ``{"type": "final" | "partial", "text": str}``
        """
        ...

    @abstractmethod
    def needs_reset(self, now: float) -> bool:
        """Check if the processor should be reset based on time elapsed."""
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        """Return processor statistics for logging."""
        ...
