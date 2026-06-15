"""Device enumeration for Linux (PulseAudio/PipeWire via pactl)."""

from __future__ import annotations

import subprocess


def list_monitor_sources() -> list[tuple[str, str]]:
    """List PulseAudio/PipeWire monitor sources.

    Returns:
        List of (name, description) tuples for monitor sources.
    """
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    sources = []
    current: dict[str, str] = {}
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("Source #"):
            if current:
                sources.append(current)
            current = {}
        if line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            current["desc"] = line.split(":", 1)[1].strip()
    if current:
        sources.append(current)

    return [
        (s["name"], s.get("desc", ""))
        for s in sources
        if "monitor" in s.get("name", "").lower()
    ]


def list_microphone_sources() -> list[tuple[str, str]]:
    """List PulseAudio/PipeWire microphone/input sources.

    Returns:
        List of (name, description) tuples for microphone sources.
    """
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    sources = []
    current: dict[str, str] = {}
    for line in out.split("\n"):
        line = line.strip()
        if line.startswith("Source #"):
            if current and "monitor" not in current.get("name", "").lower():
                sources.append(current)
            current = {}
        if line.startswith("Name:"):
            current["name"] = line.split(":", 1)[1].strip()
        elif line.startswith("Description:"):
            current["desc"] = line.split(":", 1)[1].strip()
    if current and "monitor" not in current.get("name", "").lower():
        sources.append(current)

    return [(s["name"], s.get("desc", "")) for s in sources]
