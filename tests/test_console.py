"""Unit tests for src/console.py.

Tests audio source listing, selection, amplification, and subtitle display.
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from rich.console import Console

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.console import (
    _list_monitor_sources,
    _list_microphone_sources,
    _select_source,
    _amplify,
    SubtitleDisplay
)

# ── Tests: _list_monitor_sources / _list_microphone_sources ──────────────────
def test_list_monitor_sources_success():
    mock_output = """Source #1
Name: Monitor of Speaker
Description: Output device
Source #2
Name: Monitor of Headphones
Description: Headset monitor
"""
    with patch("subprocess.check_output") as mock_sub:
        mock_sub.return_value = mock_output
        sources = _list_monitor_sources()
        assert len(sources) == 2
        assert sources[0] == ("Monitor of Speaker", "Output device")
        assert sources[1] == ("Monitor of Headphones", "Headset monitor")

def test_list_microphone_sources_success():
    mock_output = """Source #1
Name: Microphone
Description: Input device
Source #2
Name: Monitor of Speaker
Description: Output device
"""
    with patch("subprocess.check_output") as mock_sub:
        mock_sub.return_value = mock_output
        sources = _list_microphone_sources()
        assert len(sources) == 1
        assert sources[0] == ("Microphone", "Input device")

def test_list_sources_not_found():
    with patch("subprocess.check_output", side_effect=FileNotFoundError):
        assert _list_monitor_sources() == []
        assert _list_microphone_sources() == []

# ── Tests: _select_source ───────────────────────────────────────────────────────
def test_select_source_by_index():
    mock_monitor = [("Monitor 1", "Desc 1"), ("Monitor 2", "Desc 2")]
    with patch("src.console._list_monitor_sources", return_value=mock_monitor):
        assert _select_source(True, 0) == "Monitor 1"
        assert _select_source(True, 1) == "Monitor 2"
        assert _select_source(True, 5) is None

def test_select_source_interactive():
    mock_monitor = [("Monitor 1", "Desc 1"), ("Monitor 2", "Desc 2")]
    with patch("src.console._list_monitor_sources", return_value=mock_monitor):
        with patch("builtins.input", return_value="1"):
            assert _select_source(True, None) == "Monitor 2"
        with patch("builtins.input", return_value="2"):
            assert _select_source(True, None) is None

# ── Tests: _amplify ─────────────────────────────────────────────────────────────
def test_amplify():
    data = b"\x64\x00"  # Sample: 100 (little-endian)
    volume = 2.0
    expected = b"\xc8\x00" # Sample: 200
    assert _amplify(data, volume) == expected

    # Test clipping with a value that should work
    data_large = b"\x64\x00" # Sample: 100
    volume_large = 500.0
    expected_large = b'\xff\x7f' # Sample: 32767 (clipped)
    result = _amplify(data_large, volume_large)
    assert result == expected_large

# ── Tests: SubtitleDisplay ───────────────────────────────────────────────────────
def test_subtitle_display():
    console = Console()
    display = SubtitleDisplay(console)
    
    # Test update_partial
    display.update_partial("Partial text")
    assert display.partial_text == "Partial text"
    
    # Test commit_final
    display.commit_final("Final sentence")
    assert len(display.final_lines) == 1
    assert display.partial_text == ""
    
    # Test continuation
    display.commit_final("Final sentence continued")
    assert len(display.final_lines) == 1
