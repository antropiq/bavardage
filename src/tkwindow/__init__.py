"""Public API for the tkwindow transcription package.

Re-exports the main entry points so existing imports continue to work:
    from src.tkwindow import TkWindow, main, list_devices
"""

from __future__ import annotations

from .cli import main
from .window import TkWindow

__all__ = ["TkWindow", "main"]
