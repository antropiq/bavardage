"""Unit tests for src/console.py.

Tests argument parsing and main dispatch — all without requiring a real
microphone or model files.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------

def test_parser_default_engine_is_vosk():
    from src.console import _build_parser
    args = _build_parser().parse_args([])
    assert args.engine == "vosk"


def test_parser_choices():
    from src.console import _build_parser
    parser = _build_parser()
    assert "vosk" in parser.parse_args(["--engine", "vosk"]).engine
    assert "whisper" in parser.parse_args(["--engine", "whisper"]).engine


def test_parser_vosk_model_path():
    from src.console import _build_parser
    args = _build_parser().parse_args(["--vosk-model", "/path/to/model"])
    assert args.vosk_model == "/path/to/model"


def test_parser_whisper_model_default():
    from src.console import _build_parser
    args = _build_parser().parse_args([])
    assert args.whisper_model == "small"


def test_parser_whisper_language_default():
    from src.console import _build_parser
    args = _build_parser().parse_args([])
    assert args.whisper_language == "fr"


def test_parser_debug_flag():
    from src.console import _build_parser
    args = _build_parser().parse_args(["--debug"])
    assert args.debug is True


def test_parser_no_debug_flag():
    from src.console import _build_parser
    args = _build_parser().parse_args([])
    assert args.debug is False


def test_parser_all_flags():
    from src.console import _build_parser
    args = _build_parser().parse_args([
        "--engine", "whisper",
        "--whisper-model", "base",
        "--whisper-language", "en",
        "--debug",
    ])
    assert args.engine == "whisper"
    assert args.whisper_model == "base"
    assert args.whisper_language == "en"
    assert args.debug is True


# ---------------------------------------------------------------------------
# main — dispatches to correct engine
# ---------------------------------------------------------------------------

@patch("src.console._run_vosk_console")
@patch("src.console._run_whisper_console")
def test_main_dispatches_to_vosk_by_default(mock_wr, mock_vk):
    console_mod = __import__("src.console", fromlist=["main"])
    console_mod.main([])
    mock_vk.assert_called_once()
    mock_wr.assert_not_called()
    called_args = mock_vk.call_args[0][0]
    assert called_args.engine == "vosk"


@patch("src.console._run_vosk_console")
@patch("src.console.logger")
def test_main_debug_level_sets_debug(mock_logger, mock_run):
    console_mod = __import__("src.console", fromlist=["main"])
    console_mod.main(["--debug"])
    mock_logger.remove.assert_called_once()


if __name__ == "__main__":
    import traceback

    tests = [
        test_parser_default_engine_is_vosk,
        test_parser_choices,
        test_parser_vosk_model_path,
        test_parser_whisper_model_default,
        test_parser_whisper_language_default,
        test_parser_debug_flag,
        test_parser_no_debug_flag,
        test_parser_all_flags,
        test_main_dispatches_to_vosk_by_default,
        test_main_debug_level_sets_debug,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  [OK] {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  [FAIL] {test.__name__}: {exc}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
