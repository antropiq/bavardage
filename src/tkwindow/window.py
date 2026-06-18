"""Main TkWindow orchestrator class.

After OOP refactoring, this class is a thin coordinator that delegates
device listing, audio capture, rendering, and GUI construction to
specialized modules.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path

from loguru import logger
from vosk import KaldiRecognizer, Model

from .audio.base import BaseAudioCapture
from .devices import list_all_sources
from .gui import build_window
from .renderer import CanvasRenderer
from .settings import load_settings


class TkWindow:
    """Tkinter window for real-time Vosk transcription using canvas rendering.

    Orchestrates device listing, audio capture, Vosk transcription,
    and dual-canvas rendering. Platform-specific logic is delegated
    to modules in devices/ and audio/.
    """

    def __init__(
        self,
        model_path: str,
        user_speaker: bool = False,
        volume: float = 1.0,
        device: int | None = None,
        transcription_path: str | None = None,
    ) -> None:
        self.model_path = model_path
        self.user_speaker = user_speaker
        self.volume = volume
        self.device = device
        self.transcription_path = transcription_path
        self.running = False
        self.rec: KaldiRecognizer | None = None
        self.model: Model | None = None

        # Transcription state
        self._partial_text = ""
        self._last_final = ""
        self._last_partial = ""
        self._accumulated_text = ""

        # Device management
        self._sources: list[tuple[str, str, str]] = []
        self._mic_index: int | None = None
        self._speaker_index: int | None = None
        self._active_index: int = -1

        # Audio capture (platform-specific)
        self._audio_capture: BaseAudioCapture | None = None

        # DPI scale for window geometry restoration
        self._dpi_scale: float = 1.0

        # Rendering and GUI (set by build_window)
        self._renderer: CanvasRenderer | None = None
        self._controls = None
        self._root: tk.Tk | None = None
        self._max_text_items: int = 100

        # Autostart flag (loaded from settings)
        self._autostart: bool = False

    # --- Settings ---

    def _load_device_settings(self) -> None:
        """Load device indices from settings file."""
        settings = load_settings()
        self._mic_index = settings.get("micDeviceIndex")
        self._speaker_index = settings.get("speakerMonitorDeviceIndex")
        self._autostart = settings.get("autostart", False)

    def _calc_dpi_scale(self) -> float:
        """Calculate display DPI scale factor from physical vs logical pixels."""
        if not self._root:
            return 1.0
        try:
            physical = self._root.winfo_fpixels(1)
            logical = self._root.winfo_pixels(1)
            if logical > 0:
                scale = physical / logical
                return max(1.0, min(scale, 3.0))
        except Exception:
            pass
        return 1.0

    def _save_window_geometry(self) -> None:
        """Save current window geometry to settings file."""
        if not self._root:
            return
        settings = load_settings()
        geometry = self._root.geometry()
        try:
            parts = geometry.split("+")
            size_parts = parts[0].split("x")
            width, height = int(size_parts[0]), int(size_parts[1])
            left = int(parts[1]) if len(parts) > 1 else 0
            top = int(parts[2]) if len(parts) > 2 else 0
            settings["windowsPosition"] = {
                "width": width,
                "height": height,
                "left": left,
                "top": top,
            }
        except (IndexError, ValueError):
            pass
        from .settings import save_settings
        save_settings(settings)

    def _restore_window_geometry(self) -> None:
        """Restore window geometry from settings, scaled by DPI factor."""
        settings = load_settings()
        wp = settings.get("windowsPosition")
        if wp and all(k in wp for k in ("width", "height", "left", "top")):
            try:
                left = int(wp["left"] * self._dpi_scale)
                top = int(wp["top"] * self._dpi_scale)
                self._root.geometry(
                    f"{wp['width']}x{wp['height']}+{left}+{top}"
                )
            except (ValueError, TypeError):
                pass

    # --- Callbacks (bound by gui/ layer) ---

    def _toggle(self) -> None:
        """Toggle transcription start/stop."""
        if self.running:
            self._stop()
        else:
            self._start()

    def _clear(self) -> None:
        """Clear all transcription text."""
        self._partial_text = ""
        self._last_final = ""
        self._last_partial = ""
        self._accumulated_text = ""
        if self._renderer:
            self._renderer.clear()
        if self.transcription_path:
            Path(self.transcription_path).write_text("", encoding="utf-8")

    def _write_transcription(self, text: str) -> None:
        """Write accumulated transcription to the output file."""
        if not self.transcription_path:
            return
        path = Path(self.transcription_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._accumulated_text, encoding="utf-8")

    def _toggle_speaker(self) -> None:
        """Switch active device to the configured speaker monitor."""
        if self._speaker_index is None or self._speaker_index < 0 or self._speaker_index >= len(self._sources):
            return
        self._active_index = self._speaker_index
        from ttkbootstrap.constants import NORMAL, DISABLED, OUTLINE, PRIMARY
        self._controls.speaker_btn.config(state=NORMAL, bootstyle=PRIMARY)
        self._controls.mic_btn.config(
            state=NORMAL if self._mic_index is not None else DISABLED,
            bootstyle=(OUTLINE, PRIMARY),
        )

    def _toggle_mic(self) -> None:
        """Switch active device to the configured microphone."""
        if self._mic_index is None or self._mic_index < 0 or self._mic_index >= len(self._sources):
            return
        self._active_index = self._mic_index
        from ttkbootstrap.constants import NORMAL, DISABLED, OUTLINE, PRIMARY
        self._controls.mic_btn.config(state=NORMAL, bootstyle=PRIMARY)
        self._controls.speaker_btn.config(
            state=NORMAL if self._mic_index is not None else DISABLED,
            bootstyle=(OUTLINE, PRIMARY),
        )

    # --- Start / Stop ---

    def _start(self) -> None:
        """Start audio capture and transcription."""
        if self._active_index < 0 or self._active_index >= len(self._sources):
            self._controls.status_var.set("No device configured")
            return

        source_name, _, source_type = self._sources[self._active_index]
        self._controls.status_var.set(f"Starting ({source_type})...")
        self._root.update_idletasks()

        # Load Vosk model
        try:
            self.model = Model(self.model_path)
        except Exception as e:
            self._controls.status_var.set(f"Model load error: {e}")
            logger.error(f"Failed to load Vosk model: {e}")
            return

        self.rec = KaldiRecognizer(self.model, 16000)
        self.rec.SetWords(True)

        # Start audio capture (create_audio_capture starts it automatically)
        self._audio_capture = self._create_audio_capture(source_name)

        self.running = True
        self._last_final = ""
        self._last_partial = ""
        self._partial_text = ""
        self._clear()
        from ttkbootstrap.constants import DANGER, OUTLINE, SUCCESS, DISABLED, NORMAL
        self._controls.toggle_btn.config(text="Stop", bootstyle=(DANGER, OUTLINE))
        self._controls.clear_btn.config(state=DISABLED)
        self._controls.status_var.set("Listening")

        self._root.after(16, self._process_loop)

    def _stop(self) -> None:
        """Stop audio capture and transcription."""
        from ttkbootstrap.constants import SUCCESS, NORMAL, OUTLINE
        self.running = False
        if self._audio_capture:
            self._audio_capture.stop()
            self._audio_capture.close()
            self._audio_capture = None
        self.rec = None
        self._controls.toggle_btn.config(text="Start", bootstyle=(SUCCESS, OUTLINE))
        self._controls.clear_btn.config(state=NORMAL)
        self._controls.status_var.set("Stopped")

    def _create_audio_capture(self, source_name: str) -> BaseAudioCapture:
        """Create a platform-specific audio capture backend.

        Args:
            source_name: Name of the audio source to capture from.

        Returns:
            A configured BaseAudioCapture instance.
        """
        from .audio import create_audio_capture
        return create_audio_capture(source_name)

    # --- Async processing loop (runs in root.after) ---

    def _process_loop(self) -> None:
        """Process audio chunks from the capture backend."""
        if not self.running or not self._audio_capture or not self.rec:
            return

        data = self._audio_capture.read(512)  # ~32ms at 16kHz mono s16le

        if len(data) == 0:
            self._stop()
            return

        # Apply volume amplification
        if self.volume > 1.0:
            from .audio.utils.amplify import amplify
            data = amplify(data, self.volume)

        accepted = self.rec.AcceptWaveform(data)

        if accepted:
            result_str = self.rec.FinalResult()
            result = json.loads(result_str)
            text = result.get("text", "").strip()
            if text and text != self._last_final:
                self._partial_text = ""
                if self._accumulated_text:
                    self._accumulated_text += "\n" + text
                else:
                    self._accumulated_text = text
                self._last_final = text
                if self._renderer:
                    self._renderer._active_is_top = not self._renderer._active_is_top
                self._root.after(0, self._render)
        else:
            partial_str = self.rec.PartialResult()
            partial = json.loads(partial_str)
            partial_text = partial.get("partial", "").strip()
            if partial_text and partial_text != self._last_partial:
                self._partial_text = partial_text
                self._last_partial = partial_text
                self._root.after(0, self._render)

        self._root.after(16, self._process_loop)

    def _render(self) -> None:
        """Trigger ping-pong canvas rendering and write transcription file."""
        if self._renderer:
            self._renderer.render_ping_pong(self._last_final, self._partial_text)
        if self._last_final and self.transcription_path:
            self._write_transcription(self._last_final)

    # --- Entry point ---

    def run(self) -> None:
        """Build the GUI and enter the main event loop."""
        # Load settings and enumerate devices
        self._load_device_settings()
        self._sources = list_all_sources()

        # CLI --device overrides settings
        if self.device is not None and 0 <= self.device < len(self._sources):
            self._active_index = self.device
            self._autostart = True

        # Build GUI
        self._root = build_window(self)
        self._dpi_scale = self._calc_dpi_scale()
        self._restore_window_geometry()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        if self._autostart:
            self._root.after(300, self._toggle)

        self._root.mainloop()

    def _on_close(self) -> None:
        """Handle window close event."""
        if self.running:
            self._stop()
        self._save_window_geometry()
        self._root.destroy()
