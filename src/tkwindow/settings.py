"""Settings persistence for tkwindow.

Stores device indices and window geometry in ~/.bavardage/settings.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

_SETTINGS_DIR = Path.home() / ".bavardage"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


def load_settings() -> dict:
    """Load settings from ~/.bavardage/settings.json."""
    try:
        if _SETTINGS_FILE.exists():
            with open(_SETTINGS_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load settings: {e}")
    return {
        "micDeviceIndex": -1,
        "speakerMonitorDeviceIndex": -1,
        "autostart": False,
    }


def save_settings(settings: dict) -> None:
    """Save settings to ~/.bavardage/settings.json."""
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        logger.warning(f"Failed to save settings: {e}")
