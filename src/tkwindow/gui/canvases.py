"""Dual-canvas layout for transcription display.

Creates two vertically-stacked canvases with ping-pong rendering,
resize bindings, and mousewheel scrolling.
"""

from __future__ import annotations

import tkinter as tk

from ..renderer import CanvasRenderer


def create_canvases(parent: tk.Widget, max_items: int = 100) -> CanvasRenderer:
    """Create dual-canvas layout for transcription rendering.

    Args:
        parent: Parent widget to place canvases in.
        max_items: Number of pre-allocated text items per canvas.

    Returns:
        Configured CanvasRenderer instance.
    """
    renderer = CanvasRenderer(parent, max_items=max_items)

    # Bind resize events — one drives both canvases
    renderer.canvas_top.bind("<Configure>", renderer.on_configure)
    renderer.canvas_bottom.bind("<Configure>", renderer.on_configure)

    # Bind mouse wheel for scrolling
    renderer.canvas_top.bind_all("<MouseWheel>", renderer.on_mousewheel)
    renderer.canvas_bottom.bind_all("<MouseWheel>", renderer.on_mousewheel)

    return renderer
