"""SessionManager: manages WebSocket session lifecycle, deduplication, buffer, and LLM post-processing."""

from __future__ import annotations

import asyncio
import logging

from .base_engine import BaseEngine
from .transcription_buffer import TranscriptionBuffer

log = logging.getLogger(__name__)


class SessionManager:
    """Manages a single WebSocket session: audio processing, dedup, and lifecycle."""

    def __init__(
        self,
        engine: BaseEngine,
        reset_interval: float = 45.0,
        partial_word_history: int = 5,
        llm_processor=None,
        buffer_config: dict | None = None,
    ) -> None:
        self._engine = engine
        self._reset_interval = reset_interval
        self._partial_word_history = partial_word_history
        self._llm_processor = llm_processor
        self._buffer = TranscriptionBuffer(**(buffer_config or {}))
        self._recognizer = None
        self._processor = None  # initialized in _setup
        self._chunk_count = 0
        self._last_final_text: str = ""
        self._last_partial_words: list[str] = []

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    async def _setup(self) -> None:
        """Create a fresh recognizer and processor for this session."""
        self._recognizer = await self._engine.create_recognizer()
        self._processor = self._create_processor(self._recognizer)
        self._buffer = TranscriptionBuffer(
            max_buffer_size=self._buffer._max_buffer_size,
            silence_threshold=self._buffer._silence_threshold,
            min_buffer_size=self._buffer._min_buffer_size,
        )
        self._chunk_count = 0
        self._last_final_text = ""
        self._last_partial_words = []

        if self._llm_processor and self._llm_processor.enabled:
            log.debug("LLM post-processing enabled for session")

    def _create_processor(self, recognizer):
        """Create the appropriate processor based on the engine type."""
        from .vosk_engine import VoskEngine

        if isinstance(self._engine, VoskEngine):
            from .audio_processor import AudioProcessor
            return AudioProcessor(
                recognizer,
                reset_interval=self._reset_interval,
                partial_word_history=self._partial_word_history,
            )
        else:
            from .whisper_processor import WhisperProcessor
            return WhisperProcessor(
                recognizer,
                reset_interval=self._reset_interval,
            )

    async def _reset_recognizer(self) -> None:
        """Replace the recognizer and processor with fresh instances."""
        # Return old recognizer
        if self._recognizer:
            await self._engine.return_recognizer(self._recognizer)
        # Borrow a new one
        self._recognizer = await self._engine.create_recognizer()
        self._processor = self._create_processor(self._recognizer)

    async def close(self) -> None:
        """Return the recognizer, flush remaining buffer, and clean up."""
        # Flush any remaining text in the LLM buffer
        remaining = self._buffer.force_flush()
        if remaining and self._llm_processor:
            polished = await self._llm_processor.process(remaining)
            if polished:
                log.debug("LLM flushed remaining text: %s", polished)

        # Flush any remaining audio in the Whisper processor (Vosk has none)
        if hasattr(self._processor, "flush_remaining"):
            flushed = self._processor.flush_remaining()
            if flushed:
                await self._send_final(flushed)

        if self._recognizer:
            await self._engine.return_recognizer(self._recognizer)
            self._recognizer = None

    async def _send_final(self, text: str) -> None:
        """Send a final transcription result, optionally through LLM."""
        if self._llm_processor and self._llm_processor.enabled:
            try:
                polished = await self._llm_processor.process(text)
                if polished:
                    await self._ws.send_json({"type": "final", "text": polished})
                    return
            except Exception:
                pass
        try:
            await self._ws.send_json({"type": "final", "text": text})
        except Exception:
            pass

    async def handle_message(self, msg, ws, now: float) -> None:
        """Process a single WebSocket message.

        Handles ping/pong, audio chunks, and connection close.
        """
        from aiohttp import web

        # Store ws reference for close() flush
        self._ws = ws

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

        # Check if a reset is needed
        if self._processor and self._processor.needs_reset(now):
            log.debug("Resetting recognizer (chunk %d)", self._chunk_count)
            await self._reset_recognizer()
            self._processor._last_reset_time = now

        # Process audio chunk
        result = self._processor.process_chunk(data)
        if result and result["type"] == "final":
            log.info("FINAL result: %r", result["text"][:200])

            # Add fragment to buffer
            raw_text, should_flush = self._buffer.add_fragment(result["text"], now)
            log.info("Buffer: raw_text=%r should_flush=%s llm_enabled=%s",
                     raw_text[:100] if raw_text else "", should_flush,
                     self._llm_processor.enabled if self._llm_processor else False)

            try:
                if should_flush:
                    # Buffer was already cleared by add_fragment; use returned text
                    if self._llm_processor and self._llm_processor.enabled:
                        try:
                            log.info("LLM flushing buffer: %r", raw_text[:200])
                            polished_text = await self._llm_processor.process(raw_text)
                            log.info("LLM flushed: %r", polished_text[:200] if polished_text else "")
                            if polished_text:
                                await ws.send_json({"type": "final", "text": polished_text})
                                return
                        except Exception:
                            log.exception("LLM flush failed")
                    log.info("Sending raw flushed text: %r", raw_text[:200])
                    await ws.send_json({"type": "final", "text": raw_text})
                else:
                    # Process fragment through LLM when enabled
                    if self._llm_processor and self._llm_processor.enabled:
                        try:
                            log.info("LLM processing fragment: %r", result["text"][:200])
                            polished = await self._llm_processor.process(result["text"])
                            log.info("LLM processed: %r", polished[:200] if polished else "")
                            if polished:
                                await ws.send_json({"type": "final", "text": polished})
                                return
                        except Exception:
                            log.exception("LLM fragment processing failed")
                    log.info("Sending raw fragment: %r", result["text"][:200])
                    await ws.send_json({"type": "final", "text": result["text"]})
            except Exception:
                log.exception("Failed to send final result")
        elif result:
            try:
                await ws.send_json(result)
            except Exception:
                pass

    def get_stats(self) -> dict:
        """Return session statistics."""
        return {
            "chunks": self._chunk_count,
            "last_final": self._last_final_text,
        }
