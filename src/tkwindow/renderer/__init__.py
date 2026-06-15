"""Canvas rendering with ping-pong dual-canvas architecture.

Provides flicker-free text rendering using pre-allocated canvas text items.
Two canvases alternate between "active" (showing partials) and "committed"
(showing last final text).
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from .pool import ItemPool


class CanvasRenderer:
    """Manages dual-canvas ping-pong rendering for transcription display."""

    def __init__(
        self,
        parent: tk.Widget,
        max_items: int = 100,
        wrap_width: int = 600,
        font: tuple[str, int, str] | None = None,
        partial_font: tuple[str, int, str] | None = None,
        fg: str = "#ffffff",
        partial_fg: str = "#cccccc",
    ) -> None:
        self._max_items = max_items
        self._wrap_width = wrap_width
        self._font = font or ("JetBrains Mono", 12, "bold")
        self._partial_font = partial_font or ("JetBrains Mono", 12, "italic")
        self._fg = fg
        self._partial_fg = partial_fg
        self._line_height = tkfont.Font(font=self._font).metrics("linespace")
        self._active_is_top = True

        # Create canvases
        self._canvas_top = tk.Canvas(
            parent,
            highlightthickness=0,
            bd=0,
        )
        self._canvas_top.config(bg="#000000")
        self._bg_rect_top = self._canvas_top.create_rectangle(
            0, 0, 9999, 9999, fill="#000000", state="hidden"
        )

        self._canvas_bottom = tk.Canvas(
            parent,
            highlightthickness=0,
            bd=0,
        )
        self._canvas_bottom.config(bg="#000000")
        self._bg_rect_bottom = self._canvas_bottom.create_rectangle(
            0, 0, 9999, 9999, fill="#000000", state="hidden"
        )

        # Pre-allocate item pools
        self._pool_top = ItemPool(self._canvas_top, max_items, self._font, fg, wrap_width)
        self._pool_bottom = ItemPool(self._canvas_bottom, max_items, self._font, fg, wrap_width)

    @property
    def canvas_top(self) -> tk.Canvas:
        return self._canvas_top

    @property
    def canvas_bottom(self) -> tk.Canvas:
        return self._canvas_bottom

    @property
    def bg_rect_top(self) -> int:
        return self._bg_rect_top

    @property
    def bg_rect_bottom(self) -> int:
        return self._bg_rect_bottom

    @property
    def items_top(self) -> list[int | None]:
        return self._pool_top.items

    @property
    def items_bottom(self) -> list[int | None]:
        return self._pool_bottom.items

    @property
    def wrap_width(self) -> int:
        return self._wrap_width

    @wrap_width.setter
    def wrap_width(self, value: int) -> None:
        self._wrap_width = value

    def render(
        self,
        canvas: tk.Canvas,
        items: list[int | None],
        lines: list[str],
        partial: str,
    ) -> None:
        """Render text lines and optional partial text to a canvas.

        Args:
            canvas: Target canvas widget.
            items: List of text item IDs for this canvas.
            lines: Final transcription lines to display.
            partial: Partial transcription text to display after lines.
        """
        # Show black background rect
        bg_rect = self._bg_rect_top if canvas is self._canvas_top else self._bg_rect_bottom
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
                canvas.itemconfig(item, text=line, font=self._font, fill=self._fg, state="normal")
                canvas.coords(item, 10, y)
                canvas.itemconfig(item, width=self._wrap_width)
                y += self._line_height

        # 3. Draw partial text after lines
        if partial and len(lines) < len(items):
            item = items[len(lines)]
            if item:
                canvas.itemconfig(item, text=partial, font=self._partial_font, fill=self._partial_fg, state="normal")
                canvas.coords(item, 10, y)
                canvas.itemconfig(item, width=self._wrap_width)
                y += self._line_height

        # 4. Update scroll region to canvas bounds
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), canvas.winfo_height()))

    def render_ping_pong(
        self,
        last_final: str,
        partial_text: str,
    ) -> None:
        """Ping-pong canvas rendering: one shows committed final, the other shows active partials.

        Args:
            last_final: The last committed final transcription line.
            partial_text: Current partial transcription text.
        """
        if self._active_is_top:
            active_canvas, active_items = self._canvas_top, self._pool_top.items
            committed_canvas, committed_items = self._canvas_bottom, self._pool_bottom.items
        else:
            active_canvas, active_items = self._canvas_bottom, self._pool_bottom.items
            committed_canvas, committed_items = self._canvas_top, self._pool_top.items

        # Committed canvas: only the last committed final
        committed_lines = [last_final] if last_final else []
        self.render(committed_canvas, committed_items, committed_lines, "")

        # Active canvas: only current partials (no final line)
        self.render(active_canvas, active_items, [], partial_text)

    def on_configure(self, event: tk.Event) -> None:
        """Handle canvas resize events.

        Syncs wrap width and updates background rectangle for the resized canvas.
        """
        self._wrap_width = event.width - 20
        if event.widget is self._canvas_top:
            self._canvas_top.coords(self._bg_rect_top, 0, 0, event.width, event.height)
            self._canvas_top.itemconfig(self._bg_rect_top, state="normal")
        else:
            self._canvas_bottom.coords(self._bg_rect_bottom, 0, 0, event.width, event.height)
            self._canvas_bottom.itemconfig(self._bg_rect_bottom, state="normal")

    def on_mousewheel(self, event: tk.Event) -> None:
        """Handle mouse wheel scrolling for both canvases."""
        self._canvas_top.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._canvas_bottom.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def clear(self) -> None:
        """Hide all text items on both canvases."""
        self._pool_top.hide_all()
        self._pool_bottom.hide_all()

    def hide_all(self) -> None:
        """Hide all items in both pools (alias for clear)."""
        self.clear()
