"""Unit tests for server.py CLI argument parsing."""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import parse_args, main, _run_console_mode, _typer_main, ParsedArgs


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _parse(argv: list[str]) -> argparse.Namespace:
    """Helper to parse a custom argument list."""
    with patch.object(sys, "argv", ["server"] + argv):
        return parse_args(argv)


# ── Tests: Default arguments ─────────────────────────────────────────────────

def test_defaults():
    args = _parse([])
    assert args.engine == "vosk"
    assert args.vosk_model is None
    assert args.whisper_model == "small"
    assert args.whisper_language == "fr"
    assert args.whisper_device == "auto"
    assert args.llm_url is None
    assert args.llm_key is None
    assert args.llm_model == "llama3"
    assert args.llm_timeout == 15.0
    assert args.llm_buffer_max == 500
    assert args.llm_silence_threshold == 2.0
    assert args.llm_buffer_min == 20
    assert args.ssl is False
    assert args.ssl_certfile is None
    assert args.ssl_keyfile is None
    assert args.debug is False
    assert args.console is False
    assert args.window is False

# ── Tests: Engine selection ──────────────────────────────────────────────────

def test_engine_vosk():
    args = _parse(["--engine", "vosk"])
    assert args.engine == "vosk"

def test_engine_whisper():
    args = _parse(["--engine", "whisper"])
    assert args.engine == "whisper"

def test_engine_invalid_exits():
    with patch.object(sys, "argv", ["server", "--engine", "invalid"]):
        try:
            parse_args(["--engine", "invalid"])
        except SystemExit:
            pass

# ── Tests: Vosk model argument ───────────────────────────────────────────────

def test_vosk_model_default():
    args = _parse([])
    assert args.vosk_model is None

def test_vosk_model_set():
    args = _parse(["--vosk-model", "/custom/model/path"])
    assert args.vosk_model == "/custom/model/path"

def test_vosk_model_relative_path():
    args = _parse(["--vosk-model", "./vosk-model-fr-0.22"])
    assert args.vosk_model == "./vosk-model-fr-0.22"

# ── Tests: Whisper arguments ─────────────────────────────────────────────────

def test_whisper_model():
    args = _parse(["--engine", "whisper", "--whisper-model", "tiny"])
    assert args.engine == "whisper"
    assert args.whisper_model == "tiny"

def test_whisper_language():
    args = _parse(["--engine", "whisper", "--whisper-language", "en"])
    assert args.engine == "whisper"
    assert args.whisper_language == "en"

def test_whisper_device_cpu():
    args = _parse(["--engine", "whisper", "--whisper-device", "cpu"])
    assert args.engine == "whisper"
    assert args.whisper_device == "cpu"

def test_whisper_device_cuda():
    args = _parse(["--engine", "whisper", "--whisper-device", "cuda"])
    assert args.engine == "whisper"
    assert args.whisper_device == "cuda"

# ── Tests: LLM arguments ─────────────────────────────────────────────────────

def test_llm_url():
    args = _parse(["--llm-url", "http://localhost:8080"])
    assert args.llm_url == "http://localhost:8080"

def test_llm_key():
    args = _parse(["--llm-key", "my-secret"])
    assert args.llm_key == "my-secret"

def test_llm_model():
    args = _parse(["--llm-model", "mistral"])
    assert args.llm_model == "mistral"

def test_llm_timeout():
    args = _parse(["--llm-timeout", "30.0"])
    assert args.llm_timeout == 30.0

def test_llm_buffer_max():
    args = _parse(["--llm-buffer-max", "1000"])
    assert args.llm_buffer_max == 1000

def test_llm_silence_threshold():
    args = _parse(["--llm-silence-threshold", "5.0"])
    assert args.llm_silence_threshold == 5.0

def test_llm_buffer_min():
    args = _parse(["--llm-buffer-min", "50"])
    assert args.llm_buffer_min == 50

def test_all_llm_args():
    args = _parse([
        "--llm-url", "http://10.0.0.1:9000",
        "--llm-key", "key123",
        "--llm-model", "phi3",
        "--llm-timeout", "10.0",
        "--llm-buffer-max", "200",
        "--llm-silence-threshold", "3.0",
        "--llm-buffer-min", "10",
    ])
    assert args.llm_url == "http://10.0.0.1:9000"
    assert args.llm_key == "key123"
    assert args.llm_model == "phi3"
    assert args.llm_timeout == 10.0
    assert args.llm_buffer_max == 200
    assert args.llm_silence_threshold == 3.0
    assert args.llm_buffer_min == 10

# ── Tests: SSL arguments ─────────────────────────────────────────────────────

def test_ssl_flag():
    args = _parse(["--ssl"])
    assert args.ssl is True

def test_ssl_certfile():
    args = _parse(["--ssl-certfile", "/path/to/cert.pem"])
    assert args.ssl_certfile == "/path/to/cert.pem"

def test_ssl_keyfile():
    args = _parse(["--ssl-keyfile", "/path/to/key.pem"])
    assert args.ssl_keyfile == "/path/to/key.pem"

def test_ssl_all_options():
    args = _parse(["--ssl", "--ssl-certfile", "/cert.pem", "--ssl-keyfile", "/key.pem"])
    assert args.ssl is True
    assert args.ssl_certfile == "/cert.pem"
    assert args.ssl_keyfile == "/key.pem"

# ── Tests: Logging ───────────────────────────────────────────────────────────

def test_debug_flag():
    args = _parse(["--debug"])
    assert args.debug is True

# ── Tests: Console mode argument ─────────────────────────────────────────────

def test_console_flag():
    args = _parse(["--console"])
    assert args.console is True

# ── Tests: Console Mode Delegation ────────────────────────────────────────────

def test_run_console_mode_vosk():
    """Test _run_console_mode delegates to console with vosk args."""
    args = ParsedArgs(
        engine="vosk",
        vosk_model=None,
        whisper_model="small",
        whisper_language="fr",
        whisper_device="auto",
        llm_url=None,
        llm_key=None,
        llm_model="llama3",
        llm_timeout=15.0,
        llm_buffer_max=500,
        llm_silence_threshold=2.0,
        llm_buffer_min=20,
        ssl=False,
        ssl_certfile=None,
        ssl_keyfile=None,
        debug=False,
        console=False,
        user_speaker=False,
        volume=1.0,
        device=None,
        window=False,
    )
    with patch("src.console._run_vosk_console", new_callable=AsyncMock) as mock_run:
        _run_console_mode(args)
        mock_run.assert_called_once_with(args)

def test_run_console_mode_with_vosk_model():
    """Test _run_console_mode passes --vosk-model when set."""
    args = ParsedArgs(
        engine="vosk",
        vosk_model="/custom/model",
        whisper_model="small",
        whisper_language="fr",
        whisper_device="auto",
        llm_url=None,
        llm_key=None,
        llm_model="llama3",
        llm_timeout=15.0,
        llm_buffer_max=500,
        llm_silence_threshold=2.0,
        llm_buffer_min=20,
        ssl=False,
        ssl_certfile=None,
        ssl_keyfile=None,
        debug=False,
        console=False,
        user_speaker=False,
        volume=1.0,
        device=None,
        window=False,
    )
    with patch("src.console._run_vosk_console", new_callable=AsyncMock) as mock_run:
        _run_console_mode(args)
        mock_run.assert_called_once_with(args)

def test_run_console_mode_whisper():
    """Test _run_console_mode with whisper engine."""
    args = ParsedArgs(
        engine="whisper",
        vosk_model=None,
        whisper_model="tiny",
        whisper_language="en",
        whisper_device="cpu",
        llm_url=None,
        llm_key=None,
        llm_model="llama3",
        llm_timeout=15.0,
        llm_buffer_max=500,
        llm_silence_threshold=2.0,
        llm_buffer_min=20,
        ssl=False,
        ssl_certfile=None,
        ssl_keyfile=None,
        debug=False,
        console=False,
        user_speaker=False,
        volume=1.0,
        device=None,
        window=False,
    )
    with patch("src.console._run_whisper_console", new_callable=AsyncMock) as mock_run:
        _run_console_mode(args)
        mock_run.assert_called_once_with(args)

def test_run_console_mode_with_debug():
    """Test _run_console_mode passes --debug flag."""
    args = ParsedArgs(
        engine="vosk",
        vosk_model=None,
        whisper_model="small",
        whisper_language="fr",
        whisper_device="auto",
        llm_url=None,
        llm_key=None,
        llm_model="llama3",
        llm_timeout=15.0,
        llm_buffer_max=500,
        llm_silence_threshold=2.0,
        llm_buffer_min=20,
        ssl=False,
        ssl_certfile=None,
        ssl_keyfile=None,
        debug=True,
        console=False,
        user_speaker=False,
        volume=1.0,
        device=None,
        window=False,
    )
    with patch("src.console._run_vosk_console", new_callable=AsyncMock) as mock_run:
        _run_console_mode(args)
        mock_run.assert_called_once_with(args)

# ── Tests: _typer_main ───────────────────────────────────────────────────────

def test_typer_main_delegates_to_main():
    """Test _typer_main calls main()."""
    with patch("src.server.main") as mock_main:
        _typer_main()
        mock_main.assert_called_once()

def test_main_console_mode_via_typer():
    """Test main() console path when console=True."""
    from src.server_app import ServerApp

    with patch.object(ServerApp, "run") as mock_run:
        with patch("src.server.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                engine="vosk",
                vosk_model=None,
                whisper_model="small",
                whisper_language="fr",
                whisper_device="auto",
                llm_url=None,
                llm_key=None,
                llm_model="llama3",
                llm_timeout=15.0,
                llm_buffer_max=500,
                llm_silence_threshold=2.0,
                llm_buffer_min=20,
                ssl=False,
                ssl_certfile=None,
                ssl_keyfile=None,
                debug=False,
                console=True,
                window=False,
            )
            with patch("src.server._run_console_mode") as mock_console:
                main()
                mock_console.assert_called_once()
                mock_run.assert_not_called()

def test_main_server_mode_via_typer():
    """Test main() server path when console=False."""
    from src.server_app import ServerApp

    with patch.object(ServerApp, "run") as mock_run:
        with patch("src.server.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                engine="vosk",
                vosk_model=None,
                whisper_model="small",
                whisper_language="fr",
                whisper_device="auto",
                llm_url=None,
                llm_key=None,
                llm_model="llama3",
                llm_timeout=15.0,
                llm_buffer_max=500,
                llm_silence_threshold=2.0,
                llm_buffer_min=20,
                ssl=False,
                ssl_certfile=None,
                ssl_keyfile=None,
                debug=False,
                console=False,
                window=False,
            )
            main()
            mock_run.assert_called_once()

def test_typer_main_entry_point():
    """Test the if __name__ == '__main__' entry point path with valid args."""
    from src.server_app import ServerApp

    with patch.object(ServerApp, "run") as mock_run:
        with patch("src.server.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                engine="vosk",
                vosk_model=None,
                whisper_model="small",
                whisper_language="fr",
                whisper_device="auto",
                llm_url=None,
                llm_key=None,
                llm_model="llama3",
                llm_timeout=15.0,
                llm_buffer_max=500,
                llm_silence_threshold=2.0,
                llm_buffer_min=20,
                ssl=False,
                ssl_certfile=None,
                ssl_keyfile=None,
                debug=False,
                console=False,
                window=False,
            )
            main()
            mock_run.assert_called_once()
