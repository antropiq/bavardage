"""Top bar controls for the transcription window.

Source dropdown, quick-select speaker/mic buttons, Start/Stop, Clear,
and status label.
"""

from __future__ import annotations

import tkinter as tk

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from ..renderer import CanvasRenderer


class GuiControls:
    """Top bar widget controls for the transcription window."""

    def __init__(
        self,
        parent: tk.Widget,
        window,
        sources: list[tuple[str, str, str]],
        renderer: CanvasRenderer | None = None,
    ) -> None:
        self._window = window
        self._sources = sources
        self._renderer = renderer

        # Top frame: status + buttons
        self._top_frame = tk.Frame(parent, bg="#000000")
        self._top_frame.pack(fill=X, padx=15, pady=(15, 10))

        # Speaker/Mic status buttons (visual indicators)
        self._device_btn_frame = tk.Frame(self._top_frame, bg="#000000")
        self._device_btn_frame.pack(side=LEFT, padx=(12, 6))

        self._speaker_btn = ttk.Button(
            self._device_btn_frame,
            text="\U0001F50A",
            command=self._window._toggle_speaker,
            bootstyle=(OUTLINE, PRIMARY),
            width=3,
            state=DISABLED,
        )
        self._speaker_btn.pack(side=LEFT, padx=(0, 3))

        self._mic_btn = ttk.Button(
            self._device_btn_frame,
            text="\U0001F3A4",
            command=self._window._toggle_mic,
            bootstyle=(OUTLINE, PRIMARY),
            width=3,
            state=DISABLED,
        )
        self._mic_btn.pack(side=LEFT, padx=(0, 0))

        btn_frame = tk.Frame(self._top_frame, bg="#000000")
        btn_frame.pack(side=LEFT, padx=(0, 12))

        self._toggle_btn = ttk.Button(
            btn_frame,
            text="Start",
            command=self._window._toggle,
            bootstyle=(SUCCESS, OUTLINE),
            width=8,
        )
        self._toggle_btn.pack(side=LEFT, padx=(0, 6))

        self._clear_btn = ttk.Button(
            btn_frame,
            text="Clear",
            command=self._window._clear,
            bootstyle=(SECONDARY, OUTLINE),
            width=8,
            state=DISABLED,
        )
        self._clear_btn.pack(side=LEFT, padx=(0, 6))

        self._status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(
            self._top_frame,
            textvariable=self._status_var,
            font=("Inter", 10),
        )
        self.status_label.pack(side=LEFT, fill=X, expand=True, padx=(12, 0))

    @property
    def speaker_btn(self) -> ttk.Button:
        return self._speaker_btn

    @property
    def mic_btn(self) -> ttk.Button:
        return self._mic_btn

    @property
    def toggle_btn(self) -> ttk.Button:
        return self._toggle_btn

    @property
    def clear_btn(self) -> ttk.Button:
        return self._clear_btn

    @property
    def status_var(self) -> tk.StringVar:
        return self._status_var

    @property
    def top_frame(self) -> tk.Frame:
        return self._top_frame
