"""Tkinter window mode: real-time French speech transcription (Vosk only).

GUI equivalent of console.py: dropdown for source selection, Start/Stop button,
live subtitle display with committed (bold yellow) and partial (italic gray) text.
Uses parec for PipeWire/PulseAudio monitor source capture.

Rendering: canvas text items updated in-place via canvas.after() — no widget
destruction/recreation, hence no flicker.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from loguru import logger
from vosk import KaldiRecognizer, Model


def _list_monitor_sources() -> list[tuple[str, str]]:
    """List PipeWire/PulseAudio monitor sources."""
    try:
        out = subprocess.check_output(["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL)
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

    return [(s["name"], s.get("desc", "")) for s in sources if "monitor" in s.get("name", "").lower()]


def _list_microphone_sources() -> list[tuple[str, str]]:
    """List PipeWire/PulseAudio microphone/input sources."""
    try:
        out = subprocess.check_output(["pactl", "list", "sources"], text=True, stderr=subprocess.DEVNULL)
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


def _list_all_sources() -> list[tuple[str, str, str]]:
    """List all audio sources (monitor + microphone) with type tag."""
    sources: list[tuple[str, str, str]] = []
    for name, desc in _list_monitor_sources():
        sources.append((name, desc, "monitor"))
    for name, desc in _list_microphone_sources():
        sources.append((name, desc, "mic"))
    return sources


def _amplify(data: bytes, volume: float) -> bytes:
    """Amplify raw int16 PCM samples."""
    import numpy as np
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) * volume
    samples = np.clip(samples, -32768, 32767).astype(np.int16)
    return samples.tobytes()


class TkWindow:
    """Tkinter window for real-time Vosk transcription using canvas rendering.

    Uses canvas text items updated in-place via canvas.after() — no widget
    destruction/recreation, hence no flicker.
    """

    def __init__(
        self,
        model_path: str,
        user_speaker: bool = False,
        volume: float = 1.0,
        device: int | None = None,
    ) -> None:
        self.model_path = model_path
        self.user_speaker = user_speaker
        self.volume = volume
        self.device = device
        self.running = False
        self.proc: subprocess.Popen[bytes] | None = None
        self.rec: KaldiRecognizer | None = None
        self.model: Model | None = None

        self._partial_text = ""
        self._last_final = ""
        self._last_partial = ""
        self._sources: list[tuple[str, str, str]] = []
        self._speaker_idx = -1
        self._mic_idx = -1

        # Ping-pong: active canvas shows partials, committed shows final
        self.active_is_top = True

        self.canvas_top: tk.Canvas | None = None
        self.canvas_bottom: tk.Canvas | None = None
        self.items_top: list[int | None] = []
        self.items_bottom: list[int | None] = []
        self._wrap_width: int = 600
        self._max_text_items: int = 100
        self._line_height: int = 0

    # --- GUI construction ---

    def _find_speaker_device(self) -> int:
        """Return index of first device containing both 'speaker' and 'monitor' (case-insensitive)."""
        for i, (name, desc, _) in enumerate(self._sources):
            combined = f"{name} {desc}".lower()
            if "speaker" in combined and "monitor" in combined:
                return i
        return -1

    def _find_mic_device(self) -> int:
        """Return index of first device containing both 'mic' and 'source' (case-insensitive)."""
        for i, (name, desc, _) in enumerate(self._sources):
            combined = f"{name} {desc}".lower()
            if "mic" in combined and "source" in combined:
                return i
        return -1

    def _select_speaker(self) -> None:
        idx = self._find_speaker_device()
        if idx >= 0:
            self.source_combo.current(idx)
            self._update_device_buttons()

    def _select_mic(self) -> None:
        idx = self._find_mic_device()
        if idx >= 0:
            self.source_combo.current(idx)
            self._update_device_buttons()

    def _on_source_selected(self, event: tk.Event | None = None) -> None:
        self._update_device_buttons()

    def _update_device_buttons(self) -> None:
        selected = self.source_combo.current()
        if self._speaker_idx >= 0:
            self.speaker_btn.config(
                bootstyle=(SUCCESS if selected == self._speaker_idx else OUTLINE, PRIMARY),
            )
        if self._mic_idx >= 0:
            self.mic_btn.config(
                bootstyle=(SUCCESS if selected == self._mic_idx else OUTLINE, PRIMARY),
            )

    def _build_gui(self) -> ttk.Window:
        root = ttk.Window(themename="cosmo")
        root.title("Vosk Transcription")
        root.attributes("-topmost", True)
        root.minsize(480, 480)
        root.configure(bg="#000000")

        # Full-width, bottom-aligned window
        root.update_idletasks()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        wh = 480
        root.geometry(f"{sw}x{wh}+0+{sh - wh}")

        # Top frame: source selector + buttons
        top_frame = tk.Frame(root, bg="#000000")
        top_frame.pack(fill=X, padx=15, pady=(15, 10))

        source_label = ttk.Label(top_frame, text="Source:", font=("Inter", 11, "bold"))
        source_label.pack(side=LEFT)

        self.source_var = tk.StringVar()
        self.source_combo = ttk.Combobox(
            top_frame,
            textvariable=self.source_var,
            state="readonly",
            width=42,
            font=("Inter", 10),
        )
        self.source_combo.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))

        self.source_combo.bind("<<ComboboxSelected>>", self._on_source_selected)

        # Quick-select device buttons (speaker / mic)
        self._device_btn_frame = tk.Frame(top_frame, bg="#000000")
        self._device_btn_frame.pack(side=LEFT, padx=(0, 6))

        self.speaker_btn = ttk.Button(
            self._device_btn_frame,
            text="\U0001F50A",
            command=self._select_speaker,
            bootstyle=(OUTLINE, PRIMARY),
            width=3,
            state=DISABLED,
        )
        self.speaker_btn.pack(side=LEFT, padx=(0, 3))

        self.mic_btn = ttk.Button(
            self._device_btn_frame,
            text="\U0001F3A4",
            command=self._select_mic,
            bootstyle=(OUTLINE, PRIMARY),
            width=3,
            state=DISABLED,
        )
        self.mic_btn.pack(side=LEFT, padx=(0, 0))

        self._update_device_buttons()

        btn_frame = tk.Frame(top_frame, bg="#000000")
        btn_frame.pack(side=LEFT, padx=(0, 12))

        self.toggle_btn = ttk.Button(
            btn_frame,
            text="Start",
            command=self._toggle,
            bootstyle=(SUCCESS, OUTLINE),
            width=8,
        )
        self.toggle_btn.pack(side=LEFT, padx=(0, 6))

        self.clear_btn = ttk.Button(
            btn_frame,
            text="Clear",
            command=self._clear,
            bootstyle=(SECONDARY, OUTLINE),
            width=8,
            state=DISABLED,
        )
        self.clear_btn.pack(side=LEFT, padx=(0, 6))

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(
            top_frame,
            textvariable=self.status_var,
            font=("Inter", 10),
        )
        self.status_label.pack(side=LEFT)

        # Separator
        tk.Frame(root, height=2, bg="#333333").pack(fill=X, padx=15, pady=(0, 10))

         # Canvas for rendering text - vertically stacked, fills all available space
        canvas_frame = tk.Frame(root, bg="#000000")
        canvas_frame.pack(fill=BOTH, expand=True, padx=15, pady=10)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.rowconfigure(1, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas_top = tk.Canvas(
            canvas_frame,
            highlightthickness=0,
            bd=0,
        )
        self.canvas_top.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.canvas_top.config(bg="#000000")
        self.bg_rect_top = self.canvas_top.create_rectangle(0, 0, 9999, 9999, fill="#000000", state="hidden")

        self.canvas_bottom = tk.Canvas(
            canvas_frame,
            highlightthickness=0,
            bd=0,
        )
        self.canvas_bottom.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.canvas_bottom.config(bg="#000000")
        self.bg_rect_bottom = self.canvas_bottom.create_rectangle(0, 0, 9999, 9999, fill="#000000", state="hidden")

        # Bind resize events — one drives both canvases
        self.canvas_top.bind("<Configure>", self._on_canvas_configure)
        self.canvas_bottom.bind("<Configure>", self._on_canvas_configure)

        # Bind mouse wheel for scrolling
        self.canvas_top.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas_bottom.bind_all("<MouseWheel>", self._on_mousewheel)

        # Font settings (must be before pre-allocation)
        self.final_font = ("JetBrains Mono", 12, "bold")
        self.partial_font = ("JetBrains Mono", 12, "italic")
        self.final_fg = "#ffffff"
        self.partial_fg = "#cccccc"
        self._line_height = tkfont.Font(font=self.final_font).metrics("linespace")

        # Pre-allocate canvas text item pool for both canvases
        for _ in range(self._max_text_items):
            item_t = self.canvas_top.create_text(
                0, 0,
                text="",
                font=self.final_font,
                fill=self.final_fg,
                anchor="nw",
                width=self._wrap_width,
                state="hidden",
            )
            self.items_top.append(item_t)
            item_b = self.canvas_bottom.create_text(
                0, 0,
                text="",
                font=self.final_font,
                fill=self.final_fg,
                anchor="nw",
                width=self._wrap_width,
                state="hidden",
            )
            self.items_bottom.append(item_b)

        # Populate source dropdown
        self._sources = _list_all_sources()
        if self._sources:
            display = [f"[{t.upper()}] {name}" + (f" — {desc}" if desc else "") for name, desc, t in self._sources]
            self.source_combo["values"] = display
            self.source_combo.current(0)
            self.clear_btn.config(state=NORMAL)

            # Evaluate quick-select buttons
            self._speaker_idx = self._find_speaker_device()
            self._mic_idx = self._find_mic_device()
            if self._speaker_idx >= 0:
                self.speaker_btn.config(state=NORMAL)
            if self._mic_idx >= 0:
                self.mic_btn.config(state=NORMAL)
            self._update_device_buttons()

            # Hide dropdown when both speaker and mic devices are available
            if self._speaker_idx >= 0 and self._mic_idx >= 0:
                source_label.pack_forget()
                self.source_combo.pack_forget()
        else:
            self.source_combo["values"] = ("No sources found",)
            self.status_var.set("No audio sources")

        return root

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """Sync wrap width on any canvas resize."""
        self._wrap_width = event.width - 20
        if event.widget is self.canvas_top:
            self.canvas_top.coords(self.bg_rect_top, 0, 0, event.width, event.height)
            self.canvas_top.itemconfig(self.bg_rect_top, state="normal")
        else:
            self.canvas_bottom.coords(self.bg_rect_bottom, 0, 0, event.width, event.height)
            self.canvas_bottom.itemconfig(self.bg_rect_bottom, state="normal")

    def _on_mousewheel(self, event: tk.Event) -> None:
        """Handle mouse wheel scrolling."""
        self.canvas_top.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.canvas_bottom.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _render_canvas(self, canvas: tk.Canvas, items: list[int | None], lines: list[str], partial: str) -> None:
        # Show black background rect
        bg_rect = self.bg_rect_top if canvas is self.canvas_top else self.bg_rect_bottom
        canvas.itemconfig(bg_rect, state="normal")

        # 1. Hide all items in the pool
        for item in items:
            if item:
                canvas.itemconfig(item, state="hidden")

        # 2. Draw text lines (finals or last final)
        y = 10
        for i, line in enumerate(lines):
            if i >= len(items):
                break
            item = items[i]
            if item:
                canvas.itemconfig(item, text=line, font=self.final_font, fill=self.final_fg, state="normal")
                canvas.coords(item, 10, y)
                canvas.itemconfig(item, width=self._wrap_width)
                y += self._line_height

        # 3. Draw partial text after lines
        if partial and len(lines) < len(items):
            item = items[len(lines)]
            if item:
                canvas.itemconfig(item, text=partial, font=self.partial_font, fill=self.partial_fg, state="normal")
                canvas.coords(item, 10, y)
                canvas.itemconfig(item, width=self._wrap_width)
                y += self._line_height

        # 4. Update scroll region to canvas bounds (no scrolling needed)
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), canvas.winfo_height()))

    def _render(self) -> None:
        """Ping-pong canvas rendering: one shows committed final, the other shows active partials."""
        if self.active_is_top:
            active_canvas, active_items = self.canvas_top, self.items_top
            committed_canvas, committed_items = self.canvas_bottom, self.items_bottom
        else:
            active_canvas, active_items = self.canvas_bottom, self.items_bottom
            committed_canvas, committed_items = self.canvas_top, self.items_top

        # Committed canvas: only the last committed final
        committed_lines = [self._last_final] if self._last_final else []
        self._render_canvas(committed_canvas, committed_items, committed_lines, "")

        # Active canvas: only current partials (no final line)
        self._render_canvas(active_canvas, active_items, [], self._partial_text)

    # --- Start / Stop ---

    def _clear(self) -> None:
        self._partial_text = ""
        self._last_final = ""
        self._last_partial = ""
        if self.canvas_top:
            for item in self.items_top:
                if item: self.canvas_top.itemconfig(item, state="hidden")
        if self.canvas_bottom:
            for item in self.items_bottom:
                if item: self.canvas_bottom.itemconfig(item, state="hidden")

    def _toggle(self) -> None:
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        source_idx = self.source_combo.current()
        if source_idx < 0:
            self.status_var.set("No source selected")
            return

        if source_idx >= len(self._sources):
            self.status_var.set("Invalid source")
            return

        source_name, _, source_type = self._sources[source_idx]
        self.status_var.set(f"Starting ({source_type})...")
        self.root.update_idletasks()

        try:
            self.model = Model(self.model_path)
        except Exception as e:
            self.status_var.set(f"Model load error: {e}")
            logger.error(f"Failed to load Vosk model: {e}")
            return

        self.rec = KaldiRecognizer(self.model, 16000)
        self.rec.SetWords(True)

        cmd = [
            "parec", "--device", source_name,
            "--format", "s16le", "--rate", "16000", "--channels", "1",
        ]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        self.running = True
        self._last_final = ""
        self._last_partial = ""
        self._partial_text = ""
        self._clear()
        self.toggle_btn.config(text="Stop", bootstyle=(DANGER, OUTLINE))
        self.source_combo.config(state="disabled")
        self.clear_btn.config(state=DISABLED)
        self.status_var.set("Listening")

        self.root.after(16, self._process_loop)

    def _stop(self) -> None:
        self.running = False
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None
        self.rec = None
        self.toggle_btn.config(text="Start", bootstyle=(SUCCESS, OUTLINE))
        self.source_combo.config(state="readonly" if self.source_combo.winfo_viewable() else "disabled")
        self.clear_btn.config(state=NORMAL)
        self.status_var.set("Stopped")

    def _kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

    # --- Async processing loop (runs in root.after) ---

    def _process_loop(self) -> None:
        if not self.running or not self.proc or not self.rec:
            return

        try:
            data = self.proc.stdout.read(1024)
        except Exception:
            data = b""

        if len(data) == 0:
            self._stop()
            return

        if self.volume > 1.0:
            data = _amplify(data, self.volume)

        accepted = self.rec.AcceptWaveform(data)

        if accepted:
            result_str = self.rec.FinalResult()
            result = json.loads(result_str)
            text = result.get("text", "").strip()
            if text and text != self._last_final:
                self._last_final = text
                self._partial_text = ""
                self.active_is_top = not self.active_is_top
                self.root.after(0, self._render)
        else:
            partial_str = self.rec.PartialResult()
            partial = json.loads(partial_str)
            partial_text = partial.get("partial", "").strip()
            if partial_text and partial_text != self._last_partial:
                self._partial_text = partial_text
                self._last_partial = partial_text
                self.root.after(0, self._render)

        self.root.after(16, self._process_loop)

    # --- Entry point ---

    def run(self) -> None:
        self.root = self._build_gui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self) -> None:
        if self.running:
            self._stop()
        self.root.destroy()


def main(argv=None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Vosk transcription window")
    parser.add_argument("--list-devices", action="store_true", help="List available audio devices and exit")
    parser.add_argument("--vosk-model", default=None, help="Path to Vosk model (default: vosk-model-small-fr-0.22)")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG-level logging")
    parser.add_argument("--user-speaker", action="store_true", help="Capture system speaker output")
    parser.add_argument("--volume", type=float, default=1.0, help="Input volume multiplier (default: 1.0)")
    parser.add_argument("--device", type=int, default=None, help="Audio device index")
    args = parser.parse_args(argv)

    if args.list_devices:
        sources = _list_all_sources()
        if sources:
            print("=== Available audio sources ===")
            for name, desc, src_type in sources:
                print(f"  [{src_type.upper()}] {name} — {desc}")
        else:
            print("No audio sources found.")
        return

    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

    model_path = args.vosk_model or "vosk-model-small-fr-0.22"
    window = TkWindow(model_path, args.user_speaker, args.volume, args.device)
    window.run()


if __name__ == "__main__":
    main()
