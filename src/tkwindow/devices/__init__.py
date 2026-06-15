"""Device enumeration with platform-specific backends.

Unified entry point for listing audio sources across platforms.
"""

from __future__ import annotations

import sys


def list_all_sources() -> list[tuple[str, str, str]]:
    """List all audio sources (monitor + microphone) with type tag.

    Returns:
        List of (name, description, type) tuples where type is
        'monitor' or 'mic'.
    """
    if sys.platform == "win32":
        return _list_devices_windows()
    else:
        return _list_all_sources_linux()


def _list_all_sources_linux() -> list[tuple[str, str, str]]:
    """List all audio sources on Linux via pactl."""
    from .linux import list_microphone_sources, list_monitor_sources

    sources: list[tuple[str, str, str]] = []
    for name, desc in list_monitor_sources():
        sources.append((name, desc, "monitor"))
    for name, desc in list_microphone_sources():
        sources.append((name, desc, "mic"))
    return sources


def _list_devices_windows() -> list[tuple[str, str, str]]:
    """List audio devices on Windows using PyAudio/PortAudio."""
    try:
        import pyaudio
    except ImportError:
        return []

    audio = pyaudio.PyAudio()
    sources = []
    try:
        count = audio.get_device_count()
        for i in range(count):
            info = audio.get_device_info_by_index(i)
            # Only input-capable devices
            if info.get("maxInputChannels", 0) == 0:
                continue
            name = info.get("name", f"Device {i}")
            channels = info.get("maxInputChannels", 0)
            rate = info.get("defaultSampleRate", 44100)

            # Classify device type
            name_lower = name.lower()
            if any(kw in name_lower for kw in (
                "loopback", "stereo mix", "what u hear", "sum", "mix"
            )):
                dtype = "loopback"
            elif any(kw in name_lower for kw in (
                "mic", "input", "headset", "webcam", "camera"
            )):
                dtype = "mic"
            else:
                dtype = "input"

            desc = f"{channels}ch @ {rate:.0f}Hz"
            sources.append((name, desc, dtype))
    finally:
        audio.terminate()
    return sources
