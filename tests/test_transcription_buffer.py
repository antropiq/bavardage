"""Unit tests for TranscriptionBuffer."""

import asyncio
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.transcription_buffer import TranscriptionBuffer


def test_accumulates_fragments():
    buf = TranscriptionBuffer()
    text, flush = buf.add_fragment("bonjour", 0.0)
    assert text == "bonjour"
    assert flush is False

    text, flush = buf.add_fragment("comment", 0.1)
    assert text == "bonjour comment"
    assert flush is False


def test_flush_on_silence():
    buf = TranscriptionBuffer(silence_threshold=1.0, min_buffer_size=5)
    buf.add_fragment("bonjour", 0.0)
    # No silence yet
    _, flush = buf.add_fragment("comment", 0.5)
    assert flush is False
    # Silence exceeded, buffer > min
    _, flush = buf.add_fragment("allez", 2.0)
    assert flush is True


def test_flush_on_buffer_overflow():
    buf = TranscriptionBuffer(max_buffer_size=20, min_buffer_size=5)
    _, flush = buf.add_fragment("a" * 15, 0.0)
    assert flush is False
    _, flush = buf.add_fragment("b" * 10, 0.1)
    assert flush is True


def test_flush_clears_buffer():
    buf = TranscriptionBuffer()
    buf.add_fragment("test", 0.0)
    result = buf.flush()
    assert result == "test"
    assert buf.raw_text == ""
    assert buf.fragment_count == 0


def test_force_flush_returns_text():
    buf = TranscriptionBuffer()
    buf.add_fragment("remaining", 0.0)
    result = buf.force_flush()
    assert result == "remaining"
    assert buf.raw_text == ""


def test_min_buffer_prevents_early_flush():
    buf = TranscriptionBuffer(silence_threshold=0.5, min_buffer_size=50)
    buf.add_fragment("petit", 0.0)
    _, flush = buf.add_fragment("texte", 1.0)
    assert flush is False  # buffer < min_buffer_size


if __name__ == "__main__":
    test_accumulates_fragments()
    test_flush_on_silence()
    test_flush_on_buffer_overflow()
    test_flush_clears_buffer()
    test_force_flush_returns_text()
    test_min_buffer_prevents_early_flush()
    print("All TranscriptionBuffer tests passed!")


def test_buffer_integration_with_session():
    """Test buffer behavior simulating session flow."""
    buf = TranscriptionBuffer(max_buffer_size=100, silence_threshold=1.0, min_buffer_size=5)
    
    # Simulate speech fragments
    _, flush1 = buf.add_fragment("bonjour", 0.0)
    assert not flush1
    
    _, flush2 = buf.add_fragment("comment", 0.5)
    assert not flush2
    
    # Silence exceeded
    _, flush3 = buf.add_fragment("allez vous", 2.0)
    assert flush3
    
    # Buffer should be cleared after flush
    assert buf.raw_text == ""
    assert buf.fragment_count == 0
    
    # New fragments start fresh
    _, flush4 = buf.add_fragment("je voudrais", 2.5)
    assert not flush4
    assert buf.raw_text == "je voudrais"
