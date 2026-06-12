"""Unit tests for SessionManager."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.session_manager import SessionManager
from src.transcription_buffer import TranscriptionBuffer


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_engine(**kwargs):
    """Create a mock BaseEngine."""
    engine = MagicMock()
    engine.is_loaded = kwargs.get("is_loaded", True)
    engine.create_recognizer = AsyncMock(return_value=MagicMock())
    engine.return_recognizer = AsyncMock()
    engine.parse_final_result = MagicMock(return_value={"text": "test"})
    engine.parse_partial_result = MagicMock(return_value={"partial": "test"})
    engine.get_health_status = MagicMock(return_value={"status": "ready"})
    return engine


def make_vosk_engine():
    """Create a mock engine that reports as VoskEngine for _create_processor."""
    engine = make_engine()
    # Patch the VoskEngine import so _create_processor thinks it's a VoskEngine
    return engine


def make_mock_ws():
    """Create a mock aiohttp WebSocketResponse."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_str = AsyncMock()
    return ws


def make_llm_processor(enabled=True):
    """Create a mock LLMPostProcessor."""
    llm = MagicMock()
    llm.enabled = enabled
    llm.process = AsyncMock(return_value="polished text")
    return llm


def make_processor_mock():
    """Create a mock processor implementing BaseProcessor."""
    proc = MagicMock()
    proc.process_chunk = MagicMock(return_value=None)
    proc.needs_reset = MagicMock(return_value=False)
    proc.chunk_count = 0
    proc._last_reset_time = 0.0
    return proc


# ── Tests: Initialization ────────────────────────────────────────────────────

def test_init_creates_buffer():
    sm = SessionManager(make_engine())
    assert isinstance(sm._buffer, TranscriptionBuffer)
    assert sm._recognizer is None
    assert sm._processor is None
    assert sm._chunk_count == 0
    assert sm._last_final_text == ""
    assert sm._last_partial_words == []


def test_init_with_buffer_config():
    config = {"max_buffer_size": 100, "silence_threshold": 3.0, "min_buffer_size": 10}
    sm = SessionManager(make_engine(), buffer_config=config)
    assert sm._buffer._max_buffer_size == 100
    assert sm._buffer._silence_threshold == 3.0
    assert sm._buffer._min_buffer_size == 10


def test_init_with_llm_processor():
    llm = make_llm_processor()
    sm = SessionManager(make_engine(), llm_processor=llm)
    assert sm._llm_processor is llm


def test_chunk_count_property():
    sm = SessionManager(make_engine())
    assert sm.chunk_count == 0


# ── Tests: _setup ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_creates_recognizer():
    engine = make_engine()
    sm = SessionManager(engine)
    await sm._setup()
    engine.create_recognizer.assert_called_once()
    assert sm._recognizer is not None


@pytest.mark.asyncio
async def test_setup_creates_processor():
    engine = make_engine()
    sm = SessionManager(engine)
    await sm._setup()
    assert sm._processor is not None


@pytest.mark.asyncio
async def test_setup_resets_chunk_count():
    engine = make_engine()
    sm = SessionManager(engine)
    sm._chunk_count = 42
    await sm._setup()
    assert sm._chunk_count == 0


@pytest.mark.asyncio
async def test_setup_resets_last_final_text():
    engine = make_engine()
    sm = SessionManager(engine)
    sm._last_final_text = "old text"
    await sm._setup()
    assert sm._last_final_text == ""


@pytest.mark.asyncio
async def test_setup_recreates_buffer():
    engine = make_engine()
    sm = SessionManager(engine)
    sm._buffer.add_fragment("fragment", 0.0)
    assert sm._buffer.raw_text == "fragment"
    await sm._setup()
    assert sm._buffer.raw_text == ""


# ── Tests: _create_processor ─────────────────────────────────────────────────

def test_create_processor_with_vosk_engine():
    """When engine is VoskEngine, AudioProcessor is created."""
    from src.vosk_engine import VoskEngine

    real_engine = MagicMock(spec=VoskEngine)
    recognizer = MagicMock()
    sm = SessionManager(real_engine)
    processor = sm._create_processor(recognizer)
    # Should be AudioProcessor instance
    assert processor.__class__.__name__ == "AudioProcessor"


def test_create_processor_with_non_vosk_engine():
    """When engine is not VoskEngine, WhisperProcessor is created."""
    recognizer = MagicMock()
    sm = SessionManager(make_engine())
    processor = sm._create_processor(recognizer)
    # Should be WhisperProcessor instance
    assert processor.__class__.__name__ == "WhisperProcessor"


# ── Tests: _reset_recognizer ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_recognizer_returns_old():
    engine = make_engine()
    old_recognizer = MagicMock()
    sm = SessionManager(engine)
    sm._recognizer = old_recognizer
    await sm._reset_recognizer()
    engine.return_recognizer.assert_called_once_with(old_recognizer)


@pytest.mark.asyncio
async def test_reset_recognizer_borrows_new():
    engine = make_engine()
    sm = SessionManager(engine)
    sm._recognizer = MagicMock()
    await sm._setup()
    await sm._reset_recognizer()
    # Should have called create_recognizer: once from setup + once from reset
    assert engine.create_recognizer.call_count >= 2


@pytest.mark.asyncio
async def test_reset_recognizer_creates_new_processor():
    engine = make_engine()
    sm = SessionManager(engine)
    sm._recognizer = MagicMock()
    old_processor = sm._processor
    await sm._reset_recognizer()
    assert sm._processor is not old_processor


# ── Tests: close ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_returns_recognizer():
    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._recognizer = MagicMock()
    sm._ws = ws
    await sm.close()
    engine.return_recognizer.assert_called_once()


@pytest.mark.asyncio
async def test_close_clears_recognizer():
    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._recognizer = MagicMock()
    sm._ws = ws
    await sm.close()
    assert sm._recognizer is None


@pytest.mark.asyncio
async def test_close_flushes_llm_buffer():
    engine = make_engine()
    llm = make_llm_processor()
    ws = make_mock_ws()
    sm = SessionManager(engine, llm_processor=llm)
    sm._ws = ws
    sm._buffer.add_fragment("remaining text", 0.0)
    await sm.close()
    # force_flush should have been called, and LLM process should be called with remaining
    llm.process.assert_called()


@pytest.mark.asyncio
async def test_close_flushes_whisper_remaining():
    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._ws = ws
    sm._processor = MagicMock()
    sm._processor.flush_remaining = MagicMock(return_value="leftover")
    await sm.close()
    sm._processor.flush_remaining.assert_called_once()


@pytest.mark.asyncio
async def test_close_no_op_without_recognizer():
    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._ws = ws
    await sm.close()  # should not raise
    engine.return_recognizer.assert_not_called()


# ── Tests: handle_message - ping/pong ────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_ping_returns_pong():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)

    msg = MagicMock()
    msg.type = web.WSMsgType.TEXT
    msg.data = "ping"

    await sm.handle_message(msg, ws, 0.0)
    ws.send_str.assert_called_once_with("pong")


@pytest.mark.asyncio
async def test_handle_message_text_sends_to_processor():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(return_value=None)

    msg = MagicMock()
    msg.type = web.WSMsgType.TEXT
    msg.data = "hello"

    await sm.handle_message(msg, ws, 0.0)
    sm._processor.process_chunk.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_binary_sends_bytes():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(return_value=None)

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"\x00\x01\x02"

    await sm.handle_message(msg, ws, 0.0)
    sm._processor.process_chunk.assert_called_once_with(b"\x00\x01\x02")


@pytest.mark.asyncio
async def test_handle_message_closed_does_nothing():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)

    msg = MagicMock()
    msg.type = web.WSMsgType.CLOSED

    await sm.handle_message(msg, ws, 0.0)
    ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_empty_data_ignored():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b""

    await sm.handle_message(msg, ws, 0.0)
    sm._processor.process_chunk.assert_not_called()


# ── Tests: handle_message - final result ─────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_final_result_sent_to_client():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "bonjour le monde"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "final"
    assert "bonjour le monde" in call_args["text"]


@pytest.mark.asyncio
async def test_handle_message_partial_result_sent_to_client():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "partial", "text": "bonj..."}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "partial"


@pytest.mark.asyncio
async def test_handle_message_no_result_no_send():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(return_value=None)

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)
    ws.send_json.assert_not_called()


# ── Tests: handle_message - LLM post-processing ──────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_llm_polishes_final_text():
    from aiohttp import web

    engine = make_engine()
    llm = make_llm_processor()
    ws = make_mock_ws()
    # Use small buffer so overflow triggers flush
    sm = SessionManager(
        engine,
        llm_processor=llm,
        buffer_config={"max_buffer_size": 10, "min_buffer_size": 1},
    )
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "bonjour le monde"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 1.0)
    # LLM was called with the buffered text
    llm.process.assert_called()
    # Client received polished text
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["text"] == "polished text"


@pytest.mark.asyncio
async def test_handle_message_llm_fallback_on_error():
    from aiohttp import web

    engine = make_engine()
    llm = make_llm_processor()
    llm.process = AsyncMock(side_effect=Exception("LLM down"))
    ws = make_mock_ws()
    sm = SessionManager(engine, llm_processor=llm)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "raw text"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)
    # Should fall back to raw text
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["text"] == "raw text"


@pytest.mark.asyncio
async def test_handle_message_no_llm_sends_raw():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)  # no LLM
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "raw text"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["text"] == "raw text"


# ── Tests: handle_message - reset ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_triggers_reset():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine, reset_interval=1.0)
    sm._recognizer = MagicMock()
    sm._processor = make_processor_mock()
    sm._processor.needs_reset = MagicMock(return_value=True)
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "after reset"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 100.0)
    engine.create_recognizer.assert_called()
    engine.return_recognizer.assert_called()


# ── Tests: handle_message - buffer flush ─────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_buffer_overflow_flushes():
    from aiohttp import web

    engine = make_engine()
    llm = make_llm_processor()
    ws = make_mock_ws()
    sm = SessionManager(
        engine,
        llm_processor=llm,
        buffer_config={"max_buffer_size": 10, "min_buffer_size": 1},
    )
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "x" * 6}
    )

    msg1 = MagicMock()
    msg1.type = web.WSMsgType.BINARY
    msg1.data = b"audio1"
    await sm.handle_message(msg1, ws, 0.0)

    msg2 = MagicMock()
    msg2.type = web.WSMsgType.BINARY
    msg2.data = b"audio2"
    await sm.handle_message(msg2, ws, 0.1)

    # Buffer exceeded max_buffer_size, should have flushed
    ws.send_json.assert_called()


# ── Tests: get_stats ─────────────────────────────────────────────────────────

def test_get_stats():
    engine = make_engine()
    sm = SessionManager(engine)
    sm._chunk_count = 42
    sm._last_final_text = "hello"

    stats = sm.get_stats()
    assert stats["chunks"] == 42
    assert stats["last_final"] == "hello"


def test_get_stats_empty():
    engine = make_engine()
    sm = SessionManager(engine)

    stats = sm.get_stats()
    assert stats["chunks"] == 0
    assert stats["last_final"] == ""


# ── Tests: close with LLM disabled ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_with_llm_disabled():
    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine, llm_processor=None)  # No LLM at all
    sm._recognizer = MagicMock()
    sm._ws = ws
    sm._buffer.add_fragment("text", 0.0)

    await sm.close()
    # Should not call any LLM methods since llm_processor is None
    engine.return_recognizer.assert_called()


# ── Tests: _send_final helper ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_final_with_llm():
    engine = make_engine()
    llm = make_llm_processor()
    ws = make_mock_ws()
    sm = SessionManager(engine, llm_processor=llm)
    sm._ws = ws

    await sm._send_final("raw text")
    llm.process.assert_called_with("raw text")
    ws.send_json.assert_called()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["text"] == "polished text"


@pytest.mark.asyncio
async def test_handle_message_llm_sends_final_and_final_llm():
    """When LLM is enabled, both 'final' and 'final_llm' messages are sent."""
    from aiohttp import web

    engine = make_engine()
    llm = make_llm_processor()
    ws = make_mock_ws()
    sm = SessionManager(
        engine,
        llm_processor=llm,
        buffer_config={"max_buffer_size": 10, "min_buffer_size": 1},
    )
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "bonjour le monde"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 1.0)

    # Should have been called twice: once for 'final', once for 'final_llm'
    assert ws.send_json.call_count == 2

    # First call: raw 'final'
    first_call = ws.send_json.call_args_list[0][0][0]
    assert first_call["type"] == "final"
    assert first_call["text"] == "bonjour le monde"

    # Second call: LLM-corrected 'final_llm'
    second_call = ws.send_json.call_args_list[1][0][0]
    assert second_call["type"] == "final_llm"
    assert second_call["text"] == "polished text"


@pytest.mark.asyncio
async def test_handle_message_llm_fallback_sends_only_final():
    """When LLM fails, only 'final' with raw text is sent (no 'final_llm')."""
    from aiohttp import web

    engine = make_engine()
    llm = make_llm_processor()
    llm.process = AsyncMock(side_effect=Exception("LLM down"))
    ws = make_mock_ws()
    sm = SessionManager(
        engine,
        llm_processor=llm,
        buffer_config={"max_buffer_size": 10, "min_buffer_size": 1},
    )
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "raw text"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)

    # Should have been called only once: for 'final' (raw fallback)
    assert ws.send_json.call_count == 1
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "final"
    assert call_args["text"] == "raw text"


@pytest.mark.asyncio
async def test_send_final_with_llm_sends_both_messages():
    """_send_final with LLM sends 'final' then 'final_llm'."""
    engine = make_engine()
    llm = make_llm_processor()
    ws = make_mock_ws()
    sm = SessionManager(engine, llm_processor=llm)
    sm._ws = ws

    await sm._send_final("raw text")

    # Should have been called twice
    assert ws.send_json.call_count == 2

    # First call: raw 'final'
    first_call = ws.send_json.call_args_list[0][0][0]
    assert first_call["type"] == "final"
    assert first_call["text"] == "raw text"

    # Second call: LLM-corrected 'final_llm'
    second_call = ws.send_json.call_args_list[1][0][0]
    assert second_call["type"] == "final_llm"
    assert second_call["text"] == "polished text"


@pytest.mark.asyncio
async def test_send_final_without_llm_sends_only_final():
    """_send_final without LLM sends only 'final' with raw text."""
    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._ws = ws

    await sm._send_final("raw text")

    # Should have been called only once
    ws.send_json.assert_called_once()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "final"
    assert call_args["text"] == "raw text"


@pytest.mark.asyncio
async def test_handle_message_no_llm_sends_only_final():
    """Without LLM, only 'final' message is sent (no 'final_llm')."""
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)  # no LLM
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(
        return_value={"type": "final", "text": "raw text"}
    )

    msg = MagicMock()
    msg.type = web.WSMsgType.BINARY
    msg.data = b"audio"

    await sm.handle_message(msg, ws, 0.0)

    # Should have been called only once
    ws.send_json.assert_called_once()
    call_args = ws.send_json.call_args[0][0]
    assert call_args["type"] == "final"
    assert call_args["text"] == "raw text"


# ── Tests: multiple messages in sequence ─────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_multiple_audio_chunks():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)
    sm._processor = make_processor_mock()
    sm._processor.process_chunk = MagicMock(return_value=None)

    for i in range(5):
        msg = MagicMock()
        msg.type = web.WSMsgType.BINARY
        msg.data = f"audio{i}".encode()
        await sm.handle_message(msg, ws, float(i))

    assert sm._processor.process_chunk.call_count == 5


# ── Tests: store ws reference ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_stores_ws_reference():
    from aiohttp import web

    engine = make_engine()
    ws = make_mock_ws()
    sm = SessionManager(engine)

    msg = MagicMock()
    msg.type = web.WSMsgType.TEXT
    msg.data = "ping"

    await sm.handle_message(msg, ws, 0.0)
    assert hasattr(sm, "_ws")
    assert sm._ws is ws


if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v"])
    sys.exit(exit_code)
