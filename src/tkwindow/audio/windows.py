"""Audio capture for Windows using PyAudio."""

from __future__ import annotations

import sys

from loguru import logger

from .base import BaseAudioCapture


class PyAudioCapture(BaseAudioCapture):
    """Audio capture using PyAudio stream on Windows."""

    def __init__(self, source_name: str) -> None:
        self._source_name = source_name
        self._pyaudio = None
        self._stream = None

    def start(self) -> None:
        """Open PyAudio stream for capture."""
        import pyaudio

        self._pyaudio = pyaudio.PyAudio()
        # Device index resolution is handled by the caller
        # Default to device 0; the index is passed via the source
        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=0,
            frames_per_buffer=1600,
        )

    def stop(self) -> None:
        """Close PyAudio stream and terminate PyAudio."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

    def read(self, frames: int) -> bytes:
        """Read audio data from PyAudio stream.

        Args:
            frames: Number of samples to read.

        Returns:
            Raw PCM bytes from the stream.
        """
        if not self._stream:
            return b""
        try:
            return self._stream.read(frames, exception_on_overflow=False)
        except Exception:
            return b""

    def close(self) -> None:
        """Release resources."""
        self.stop()
