"""BaseEngine: abstract interface for STT transcription engines.

All transcription engines (Vosk, Whisper, etc.) must implement this interface
to be plug-and-play interchangeable in the server pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseEngine(ABC):
    """Abstract base class defining the transcription engine interface.

    Public contract:
    - ``load()``: Load the model (blocking). Must be called before any
      recognizer creation.
    - ``is_loaded``: Whether the model is ready.
    - ``create_recognizer()``: Create/borrow a recognizer instance.
    - ``return_recognizer()``: Return a recognizer to the pool (if pooled).
    - ``parse_final_result()``: Parse a final transcription result dict.
    - ``parse_partial_result()``: Parse a partial transcription result dict.
    - ``get_health_status()``: Return a dict with a ``status`` key for the
      ``/health`` endpoint.
    """

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Whether the model has been loaded and is ready."""
        ...

    @abstractmethod
    def load(self) -> None:
        """Load the model. May block until ready."""
        ...

    @abstractmethod
    async def create_recognizer(self) -> Any:
        """Create or borrow a recognizer instance for a new session."""
        ...

    @abstractmethod
    async def return_recognizer(self, recognizer: Any) -> None:
        """Return a recognizer to the pool for reuse."""
        ...

    @abstractmethod
    def parse_final_result(self, result_str: str) -> dict | None:
        """Parse and validate a final result JSON string.

        Returns a dict with at least ``{"text": str}`` or ``None`` if
        the text is empty/invalid.
        """
        ...

    @abstractmethod
    def parse_partial_result(self, partial_str: str) -> dict | None:
        """Parse and validate a partial result JSON string.

        Returns a dict or ``None`` on failure.
        """
        ...

    @abstractmethod
    def get_health_status(self) -> dict:
        """Return health status dict for the ``/health`` endpoint."""
        ...
