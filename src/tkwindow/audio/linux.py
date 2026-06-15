"""PulseAudio/PipeWire audio capture via parec subprocess."""

from __future__ import annotations

import signal
import subprocess
import sys

from loguru import logger

from .base import BaseAudioCapture


class PulseAudioCapture(BaseAudioCapture):
    """Audio capture using parec subprocess on Linux."""

    def __init__(self, source_name: str) -> None:
        self._source_name = source_name
        self._proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        """Start parec subprocess capturing from the given source."""
        cmd = [
            "parec", "--device", self._source_name,
            "--format", "s16le", "--rate", "16000", "--channels", "1",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )

    def stop(self) -> None:
        """Stop parec subprocess gracefully."""
        if self._proc and self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None

    def read(self, frames: int) -> bytes:
        """Read audio data from parec stdout.

        Args:
            frames: Number of samples to read (ignored, reads from pipe).

        Returns:
            Raw PCM bytes, or empty bytes if capture has ended.
        """
        if not self._proc:
            return b""
        try:
            data = self._proc.stdout.read(frames * 2)  # frames in samples, *2 for bytes
        except Exception:
            data = b""
        return data

    def close(self) -> None:
        """Release resources."""
        self.stop()
