"""SessionManager: manages WebSocket session lifecycle, deduplication, and heartbeat tracking."""

from __future__ import annotations

import asyncio
import logging

from vosk import KaldiRecognizer

log = logging.getLogger(__name__)


class SessionManager:
    """Manages a single WebSocket session: audio processing, dedup, and lifecycle."""

    def __init__(
        self,
        engine,
        reset_interval: float = 45.0,
        partial_word_history: int = 5,
    ) -> None:
        self._engine = engine
        self._reset_interval = reset_interval
        self._partial_word_history = partial_word_history
        self._recognizer: KaldiRecognizer | None = None
        self._processor = None  # initialized in _setup
        self._chunk_count = 0
        self._last_final_text: str = ""
        self._last_partial_words: list[str] = []

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    async def _setup(self) -> None:
        """Create a fresh recognizer and processor for this session (borrows from pool)."""
        self._recognizer = await self._engine.create_recognizer()
        self._processor = self._create_processor(self._recognizer)
        self._chunk_count = 0
        self._last_final_text = ""
        self._last_partial_words = []

    def _create_processor(self, recognizer: KaldiRecognizer):
        """Create an AudioProcessor instance (imported lazily to avoid circular deps)."""
        from .audio_processor import AudioProcessor
        return AudioProcessor(
            recognizer,
            reset_interval=self._reset_interval,
            partial_word_history=self._partial_word_history,
        )

    async def _reset_recognizer(self) -> None:
        """Replace the recognizer and processor with fresh instances from the pool."""
        # Return old recognizer to pool
        if self._recognizer:
            await self._engine.return_recognizer(self._recognizer)
        # Borrow a new one
        self._recognizer = await self._engine.create_recognizer()
        self._processor = self._create_processor(self._recognizer)

    async def close(self) -> None:
        """Return the recognizer to the pool and clean up."""
        if self._recognizer:
            await self._engine.return_recognizer(self._recognizer)
            self._recognizer = None

    async def handle_message(self, msg, ws, now: float) -> None:
        """Process a single WebSocket message.

        Handles ping/pong, audio chunks, and connection close.
        """
        from aiohttp import web

        if msg.type == web.WSMsgType.TEXT:
            if msg.data == "ping":
                await ws.send_str("pong")
                return
            data = msg.data.encode("utf-8")
        elif msg.type == web.WSMsgType.BINARY:
            data = bytes(msg.data)
        elif msg.type == web.WSMsgType.CLOSED:
            return
        else:
            return

        if not data or len(data) == 0:
            return

        # Check if a reset is needed (handled here to coordinate pool return/borrow)
        if self._processor and self._processor.needs_reset(now):
            log.info("Resetting Vosk recognizer (chunk %d)", self._chunk_count)
            await self._reset_recognizer()
            self._processor._last_reset_time = now

        # Process audio chunk
        result = self._processor.process_chunk(data)
        if result:
            await ws.send_json(result)

    def get_stats(self) -> dict:
        """Return session statistics."""
        return {
            "chunks": self._chunk_count,
            "last_final": self._last_final_text,
        }
