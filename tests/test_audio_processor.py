"""Unit tests for AudioProcessor."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audio_processor import AudioProcessor


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_recognizer_mock(final_result=None, partial_result=None, accepted=True):
    """Create a mock KaldiRecognizer."""
    recognizer = MagicMock()
    recognizer.AcceptWaveform = MagicMock(return_value=accepted)
    if final_result is not None:
        recognizer.FinalResult = MagicMock(return_value=final_result)
    else:
        recognizer.FinalResult = MagicMock(return_value=make_final_json(""))
    if partial_result is not None:
        recognizer.PartialResult = MagicMock(return_value=partial_result)
    else:
        recognizer.PartialResult = MagicMock(return_value=make_partial_json(""))
    return recognizer


def make_final_json(text: str) -> str:
    return json.dumps({"text": text})


def make_partial_json(text: str) -> str:
    return json.dumps({"partial": text})


# ── Tests: Initialization ────────────────────────────────────────────────────

def test_init_sets_recognizer():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._recognizer is rec


def test_init_default_reset_interval():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._reset_interval == 45.0


def test_init_custom_reset_interval():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, reset_interval=60.0)
    assert proc._reset_interval == 60.0


def test_init_default_partial_word_history():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._partial_word_history == 5


def test_init_custom_partial_word_history():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, partial_word_history=10)
    assert proc._partial_word_history == 10


def test_init_chunk_count_starts_at_zero():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc.chunk_count == 0


def test_init_last_reset_time_is_zero():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._last_reset_time == 0.0


def test_init_last_final_text_empty():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._last_final_text == ""


def test_init_last_partial_words_empty():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._last_partial_words == []


# ── Tests: chunk_count property ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunk_count_increments():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio1")
    assert proc.chunk_count == 1
    await proc.process_chunk(b"audio2")
    assert proc.chunk_count == 2


# ── Tests: needs_reset ───────────────────────────────────────────────────────

def test_needs_reset_within_interval():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, reset_interval=45.0)
    proc._last_reset_time = 0.0
    assert proc.needs_reset(10.0) is False


def test_needs_reset_at_interval():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, reset_interval=45.0)
    proc._last_reset_time = 0.0
    assert proc.needs_reset(45.0) is True


def test_needs_reset_past_interval():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, reset_interval=45.0)
    proc._last_reset_time = 100.0
    assert proc.needs_reset(200.0) is True


def test_needs_reset_custom_interval():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, reset_interval=10.0)
    proc._last_reset_time = 0.0
    assert proc.needs_reset(9.9) is False
    assert proc.needs_reset(10.0) is True


def test_needs_reset_after_manual_reset():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec, reset_interval=45.0)
    proc._last_reset_time = 100.0
    assert proc.needs_reset(100.0) is False  # 0 < 45
    assert proc.needs_reset(144.9) is False  # 44.9 < 45
    assert proc.needs_reset(145.0) is True  # 45 >= 45


# ── Tests: process_chunk - accepted (final) ──────────────────────────────────

@pytest.mark.asyncio
async def test_process_chunk_accepted_returns_final():
    rec = make_recognizer_mock(
        final_result=make_final_json("bonjour le monde"),
        accepted=True,
    )
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result == {"type": "final", "text": "bonjour le monde"}


@pytest.mark.asyncio
async def test_process_chunk_accepted_increments_counter():
    rec = make_recognizer_mock(final_result=make_final_json("test"))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio")
    assert proc.chunk_count == 1


@pytest.mark.asyncio
async def test_process_chunk_accepted_calls_accept_waveform():
    rec = make_recognizer_mock(final_result=make_final_json("test"))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio data")
    rec.AcceptWaveform.assert_called_once_with(b"audio data")


@pytest.mark.asyncio
async def test_process_chunk_accepted_calls_final_result():
    rec = make_recognizer_mock(final_result=make_final_json("test"))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio")
    rec.FinalResult.assert_called_once()


@pytest.mark.asyncio
async def test_process_chunk_accepted_stores_last_final_text():
    rec = make_recognizer_mock(final_result=make_final_json("hello world"))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio")
    assert proc._last_final_text == "hello world"


@pytest.mark.asyncio
async def test_process_chunk_accepted_strips_text():
    rec = make_recognizer_mock(final_result=make_final_json("  hello  "))
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result["text"] == "hello"


# ── Tests: process_chunk - accepted, empty text ──────────────────────────────

@pytest.mark.asyncio
async def test_process_chunk_accepted_empty_text_returns_none():
    rec = make_recognizer_mock(final_result=make_final_json("  "))
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result is None


@pytest.mark.asyncio
async def test_process_chunk_accepted_duplicate_text_returns_none():
    rec = make_recognizer_mock(final_result=make_final_json("same text"))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio1")  # first call sets _last_final_text
    assert proc._last_final_text == "same text"
    result = await proc.process_chunk(b"audio2")  # duplicate
    assert result is None


@pytest.mark.asyncio
async def test_process_chunk_accepted_new_text_returns_final():
    rec = make_recognizer_mock(final_result=make_final_json(""))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio1")  # empty final result, sets _last_final_text = ""
    rec.FinalResult.return_value = make_final_json("new text")
    result = await proc.process_chunk(b"audio2")
    assert result == {"type": "final", "text": "new text"}


# ── Tests: process_chunk - accepted, bad JSON ────────────────────────────────

@pytest.mark.asyncio
async def test_process_chunk_accepted_bad_json_returns_none():
    rec = make_recognizer_mock(final_result="not valid json{{{")
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result is None


@pytest.mark.asyncio
async def test_process_chunk_accepted_missing_text_key_returns_none():
    rec = make_recognizer_mock(final_result=json.dumps({"no_text": "here"}))
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result is None


# ── Tests: process_chunk - not accepted (partial) ────────────────────────────

@pytest.mark.asyncio
async def test_process_chunk_not_accepted_returns_partial():
    rec = make_recognizer_mock(
        partial_result=make_partial_json("bonj..."),
        accepted=False,
    )
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result == {"type": "partial", "text": "bonj..."}


@pytest.mark.asyncio
async def test_process_chunk_not_accepted_calls_partial_result():
    rec = make_recognizer_mock(partial_result=make_partial_json("test"), accepted=False)
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio")
    rec.PartialResult.assert_called_once()


@pytest.mark.asyncio
async def test_process_chunk_not_accepted_strips_text():
    rec = make_recognizer_mock(partial_result=make_partial_json("  hello  "), accepted=False)
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result["text"] == "hello"


@pytest.mark.asyncio
async def test_process_chunk_not_accepted_empty_returns_none():
    rec = make_recognizer_mock(partial_result=make_partial_json("  "))
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result is None


@pytest.mark.asyncio
async def test_process_chunk_not_accepted_bad_json_returns_none():
    rec = make_recognizer_mock(partial_result="not json")
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result is None


@pytest.mark.asyncio
async def test_process_chunk_not_accepted_missing_partial_key_returns_none():
    rec = make_recognizer_mock(partial_result=json.dumps({"no_partial": "here"}))
    proc = AudioProcessor(rec)
    result = await proc.process_chunk(b"audio")
    assert result is None


# ── Tests: partial deduplication ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_partial_deduplication_same_tail():
    """When last N words match, partial is suppressed."""
    rec = make_recognizer_mock(partial_result=make_partial_json("bonjour comment allez vous"), accepted=False)
    proc = AudioProcessor(rec, partial_word_history=4)
    await proc.process_chunk(b"audio1")  # establishes tail
    assert proc._last_partial_words == ["bonjour", "comment", "allez", "vous"]
    # Same tail again → suppressed
    rec.PartialResult = MagicMock(return_value=make_partial_json("bonjour comment allez vous"))
    result = await proc.process_chunk(b"audio2")
    assert result is None


@pytest.mark.asyncio
async def test_partial_deduplication_different_tail():
    """When tail changes, partial is returned."""
    rec = make_recognizer_mock(partial_result=make_partial_json("hello world"), accepted=False)
    proc = AudioProcessor(rec, partial_word_history=2)
    await proc.process_chunk(b"audio1")
    # Different tail
    rec.PartialResult = MagicMock(return_value=make_partial_json("hello there world"))
    result = await proc.process_chunk(b"audio2")
    assert result == {"type": "partial", "text": "hello there world"}
    assert proc._last_partial_words == ["there", "world"]


@pytest.mark.asyncio
async def test_partial_deduplication_less_than_history():
    """When fewer words than history, all words are compared."""
    rec = make_recognizer_mock(partial_result=make_partial_json("hi"), accepted=False)
    proc = AudioProcessor(rec, partial_word_history=5)
    await proc.process_chunk(b"audio1")
    assert proc._last_partial_words == ["hi"]
    # Same tail → suppressed
    rec.PartialResult = MagicMock(return_value=make_partial_json("hi"))
    result = await proc.process_chunk(b"audio2")
    assert result is None


@pytest.mark.asyncio
async def test_partial_deduplication_growing_text():
    """Partial text grows — tail should update."""
    rec = make_recognizer_mock(partial_result=make_partial_json("bon"), accepted=False)
    proc = AudioProcessor(rec, partial_word_history=3)
    await proc.process_chunk(b"audio1")
    assert proc._last_partial_words == ["bon"]

    rec.PartialResult = MagicMock(return_value=make_partial_json("bonjour le"))
    result = await proc.process_chunk(b"audio2")
    assert result == {"type": "partial", "text": "bonjour le"}
    assert proc._last_partial_words == ["bonjour", "le"]


@pytest.mark.asyncio
async def test_partial_deduplication_empty_partial_does_not_affect_tail():
    """Empty partial should not update _last_partial_words."""
    rec = make_recognizer_mock(partial_result=make_partial_json("hello"), accepted=False)
    proc = AudioProcessor(rec, partial_word_history=2)
    await proc.process_chunk(b"audio1")
    assert proc._last_partial_words == ["hello"]

    rec.PartialResult = MagicMock(return_value=make_partial_json("  "))
    result = await proc.process_chunk(b"audio2")
    assert result is None
    # Tail should be unchanged
    assert proc._last_partial_words == ["hello"]


# ── Tests: _handle_accepted directly ─────────────────────────────────────────

def test_handle_accepted_valid():
    rec = make_recognizer_mock(final_result=make_final_json("test phrase"))
    proc = AudioProcessor(rec)
    result = proc._handle_accepted()
    assert result == {"type": "final", "text": "test phrase"}


def test_handle_accepted_empty():
    rec = make_recognizer_mock(final_result=make_final_json(""))
    proc = AudioProcessor(rec)
    assert proc._handle_accepted() is None


def test_handle_accepted_duplicate():
    rec = make_recognizer_mock(final_result=make_final_json("dup"))
    proc = AudioProcessor(rec)
    proc._handle_accepted()
    assert proc._handle_accepted() is None


def test_handle_accepted_json_decode_error():
    rec = make_recognizer_mock(final_result="{invalid")
    proc = AudioProcessor(rec)
    assert proc._handle_accepted() is None


# ── Tests: _handle_partial directly ──────────────────────────────────────────

def test_handle_partial_valid():
    rec = make_recognizer_mock(partial_result=make_partial_json("partial text"))
    proc = AudioProcessor(rec)
    result = proc._handle_partial()
    assert result == {"type": "partial", "text": "partial text"}


def test_handle_partial_empty():
    rec = make_recognizer_mock(partial_result=make_partial_json(""))
    proc = AudioProcessor(rec)
    assert proc._handle_partial() is None


def test_handle_partial_json_decode_error():
    rec = make_recognizer_mock(partial_result="not json")
    proc = AudioProcessor(rec)
    assert proc._handle_partial() is None


# ── Tests: _parse_result ─────────────────────────────────────────────────────

def test_parse_result_valid_json():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    result = proc._parse_result('{"text": "hello"}', is_final=True)
    assert result == {"text": "hello"}


def test_parse_result_invalid_json():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert proc._parse_result("not json", is_final=True) is None


def test_parse_result_missing_text_key():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    result = proc._parse_result('{"nope": "here"}', is_final=True)
    assert result == {"nope": "here"}  # parses fine, caller checks for "text"


# ── Tests: get_stats ─────────────────────────────────────────────────────────

def test_get_stats_empty():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    stats = proc.get_stats()
    assert stats == {"chunks": 0, "last_final": ""}


@pytest.mark.asyncio
async def test_get_stats_with_data():
    rec = make_recognizer_mock(final_result=make_final_json("hello world"))
    proc = AudioProcessor(rec)
    await proc.process_chunk(b"audio")
    stats = proc.get_stats()
    assert stats["chunks"] == 1
    assert stats["last_final"] == "hello world"


@pytest.mark.asyncio
async def test_get_stats_after_multiple_chunks():
    rec = make_recognizer_mock(final_result=make_final_json("test"))
    proc = AudioProcessor(rec)
    for _ in range(5):
        await proc.process_chunk(b"audio")
    stats = proc.get_stats()
    assert stats["chunks"] == 5


# ── Tests: _reset_recognizer ─────────────────────────────────────────────────

def test_reset_recognizer_is_noop():
    """_reset_recognizer is intentionally a no-op; real reset is in SessionManager."""
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    # Should not raise
    proc._reset_recognizer()
    # Recognizer should be untouched
    rec.AcceptWaveform.assert_not_called()


# ── Tests: mixed final and partial ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_mixed_final_and_partial():
    """Process both accepted and non-accepted chunks."""
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)

    # First chunk: partial
    rec.AcceptWaveform.return_value = False
    rec.PartialResult.return_value = make_partial_json("bonj...")
    r1 = await proc.process_chunk(b"audio1")
    assert r1 == {"type": "partial", "text": "bonj..."}

    # Second chunk: accepted (final)
    rec.AcceptWaveform.return_value = True
    rec.FinalResult.return_value = make_final_json("bonjour le monde")
    r2 = await proc.process_chunk(b"audio2")
    assert r2 == {"type": "final", "text": "bonjour le monde"}

    assert proc.chunk_count == 2


@pytest.mark.asyncio
async def test_final_before_partial():
    """Order: final then partial."""
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)

    # Final
    rec.AcceptWaveform.return_value = True
    rec.FinalResult.return_value = make_final_json("first")
    await proc.process_chunk(b"a")

    # Partial
    rec.AcceptWaveform.return_value = False
    rec.PartialResult.return_value = make_partial_json("sec...")
    r2 = await proc.process_chunk(b"b")
    assert r2 == {"type": "partial", "text": "sec..."}


# ── Tests: acceptance toggling ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acceptance_toggle_multiple_times():
    """Alternate accepted/not accepted."""
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)

    for i in range(6):
        rec.AcceptWaveform.return_value = (i % 2 == 0)
        if i % 2 == 0:
            rec.FinalResult.return_value = make_final_json(f"final {i}")
        else:
            rec.PartialResult.return_value = make_partial_json(f"partial {i}")
        await proc.process_chunk(b"audio")

    assert proc.chunk_count == 6


# ── Tests: BaseProcessor interface conformance ───────────────────────────────

def test_is_subclass_of_base_processor():
    from src.base_processor import BaseProcessor
    assert issubclass(AudioProcessor, BaseProcessor)


def test_implements_chunk_count():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert hasattr(proc, "chunk_count")
    assert callable(getattr(type(proc), "chunk_count", None)) or isinstance(
        getattr(type(proc), "chunk_count", None), property
    )


def test_implements_process_chunk():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert callable(proc.process_chunk)


def test_implements_needs_reset():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert callable(proc.needs_reset)


def test_implements_get_stats():
    rec = make_recognizer_mock()
    proc = AudioProcessor(rec)
    assert callable(proc.get_stats)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
