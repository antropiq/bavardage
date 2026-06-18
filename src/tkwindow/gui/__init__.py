"""GUI construction for the transcription window.

Assembles canvases, controls, and wiring into a configured TkWindow.
"""

from __future__ import annotations

import os
import tkinter as tk

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, X

from ..renderer import CanvasRenderer
from .canvases import create_canvases
from .controls import GuiControls


def build_window(window) -> tk.Tk:
    """Build and return the Tkinter root window with all widgets.

    Args:
        window: TkWindow instance to wire callbacks to.

    Returns:
        Configured ttk.Window root instance.
    """
    root = ttk.Window(themename="darkly")
    root.title("Bavardage")
    root.attributes("-topmost", True)
    root.minsize(340, 240)
    root.configure(bg="#000000")

    # Set window icon
    icon_path = _resolve_icon_path()
    try:
        icon = tk.PhotoImage(file=icon_path)
        root.iconphoto(True, icon)
        root._icon = icon  # prevent garbage collection
    except Exception:
        pass

    # Create controls (top bar)
    controls = GuiControls(
        root, window, window._sources, None
    )

    # Separator
    tk.Frame(root, height=2, bg="#333333").pack(fill=X, padx=15, pady=(0, 10))

    # Create canvases (fills remaining space)
    canvas_frame = tk.Frame(root, bg="#000000")
    canvas_frame.pack(fill=BOTH, expand=True, padx=15, pady=10)
    canvas_frame.rowconfigure(0, weight=1)
    canvas_frame.rowconfigure(1, weight=1)
    canvas_frame.columnconfigure(0, weight=1)

    # Embed canvases in the frame
    renderer = CanvasRenderer(canvas_frame, max_items=window._max_text_items)
    renderer.canvas_top.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
    renderer.canvas_bottom.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

    # Bind resize events on the embedded canvases
    renderer.canvas_top.bind("<Configure>", renderer.on_configure)
    renderer.canvas_bottom.bind("<Configure>", renderer.on_configure)

    # Bind mouse wheel for scrolling
    renderer.canvas_top.bind_all("<MouseWheel>", renderer.on_mousewheel)
    renderer.canvas_bottom.bind_all("<MouseWheel>", renderer.on_mousewheel)

    # Wire references back to window
    window._renderer = renderer
    window._controls = controls

    # Set initial device button states
    _update_device_buttons(window, controls)

    return root


def _resolve_icon_path() -> str:
    """Resolve the path to the bavardage.png icon."""
    # For package: src/tkwindow/ -> resources/
    base = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base, "..", "..", "..", "resources", "bavardage.png")
    if not os.path.exists(icon_path):
        # Fallback for PyInstaller bundled app
        icon_path = os.path.join(base, "..", "resources", "bavardage.png")
    if not os.path.exists(icon_path):
        # Fallback for single-file mode
        icon_path = os.path.join(base, "..", "..", "resources", "bavardage.png")
    return icon_path


def _update_device_buttons(window, controls: GuiControls) -> None:
    """Update speaker/mic button states based on configured device indices."""
    from ttkbootstrap.constants import NORMAL, DISABLED, OUTLINE, PRIMARY
    # CLI --device takes precedence over settings
    if window.device is not None and 0 <= window.device < len(window._sources):
        window._active_index = window.device
        controls.toggle_btn.config(state=NORMAL)
        controls.clear_btn.config(state=NORMAL)
        return
    if window._speaker_index is not None and 0 <= window._speaker_index < len(window._sources):
        window._active_index = window._speaker_index
        controls.speaker_btn.config(state=NORMAL, bootstyle=PRIMARY)
        controls.mic_btn.config(
            state=NORMAL if window._mic_index is not None else DISABLED,
            bootstyle=(OUTLINE, PRIMARY),
        )
    elif window._mic_index is not None and 0 <= window._mic_index < len(window._sources):
        window._active_index = window._mic_index
        controls.mic_btn.config(state=NORMAL, bootstyle=PRIMARY)
        controls.speaker_btn.config(
            state=NORMAL if window._speaker_index is not None else DISABLED,
            bootstyle=(OUTLINE, PRIMARY),
        )
    else:
        controls.status_var.set("No device configured — use --list-devices to find device IDs")
        controls.toggle_btn.config(state=DISABLED)
        controls.speaker_btn.config(state=DISABLED)
        controls.mic_btn.config(state=DISABLED)

    controls.clear_btn.config(state=NORMAL)
