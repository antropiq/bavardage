"""Audio capture factory.

Creates platform-specific audio capture backends.
"""

from __future__ import annotations

import sys

from .base import BaseAudioCapture

def create_audio_capture(source_name: str) -> BaseAudioCapture:
    """Create an audio capture backend for the current platform.

    Args:
        source_name: Name of the audio source to capture from.

    Returns:
        A platform-specific BaseAudioCapture instance.
    """
    if sys.platform == "win32":
        from .windows import PyAudioCapture
        capture = PyAudioCapture(source_name)
    else:
        from .linux import PulseAudioCapture
        capture = PulseAudioCapture(source_name)

    capture.start()
    return capture
