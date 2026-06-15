"""Abstract base class for audio capture."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAudioCapture(ABC):
    """Abstract interface for audio capture backends."""

    @abstractmethod
    def start(self) -> None:
        """Start audio capture."""

    @abstractmethod
    def stop(self) -> None:
        """Stop audio capture gracefully."""

    @abstractmethod
    def read(self, frames: int) -> bytes:
        """Read audio data.

        Args:
            frames: Number of samples to read.

        Returns:
            Raw PCM bytes (s16le, mono).
        """

    @abstractmethod
    def close(self) -> None:
        """Release all resources."""
