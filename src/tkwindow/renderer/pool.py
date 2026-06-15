"""Canvas text item pool for pre-allocation."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont


class ItemPool:
    """Pre-allocates canvas text items for flicker-free rendering."""

    def __init__(
        self,
        canvas: tk.Canvas,
        max_items: int,
        font: tuple[str, int, str],
        fill: str,
        wrap_width: int,
    ) -> None:
        self._canvas = canvas
        self._items: list[int | None] = []

        for _ in range(max_items):
            item = canvas.create_text(
                0, 0,
                text="",
                font=font,
                fill=fill,
                anchor="nw",
                width=wrap_width,
                state="hidden",
            )
            self._items.append(item)

    @property
    def items(self) -> list[int | None]:
        """List of canvas text item IDs."""
        return self._items

    @property
    def canvas(self) -> tk.Canvas:
        """The canvas these items belong to."""
        return self._canvas

    def hide_all(self) -> None:
        """Hide all items in the pool."""
        for item in self._items:
            if item:
                self._canvas.itemconfig(item, state="hidden")

    def show_item(
        self,
        index: int,
        text: str,
        font: tuple[str, int, str],
        fill: str,
        x: int,
        y: int,
        wrap_width: int,
    ) -> None:
        """Show and configure a single item."""
        if index >= len(self._items):
            return
        item = self._items[index]
        if item:
            self._canvas.itemconfig(item, text=text, font=font, fill=fill, state="normal")
            self._canvas.coords(item, x, y)
            self._canvas.itemconfig(item, width=wrap_width)

    @property
    def size(self) -> int:
        """Number of items in the pool."""
        return len(self._items)
