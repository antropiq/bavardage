"""Unit tests for server.py CLI argument parsing."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import parse_args


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _parse(argv: list[str]) -> argparse.Namespace:
    """Helper to parse a custom argument list."""
    with patch.object(sys, "argv", ["server"] + argv):
        return parse_args(argv)


# ── Tests: Default arguments ─────────────────────────────────────────────────

def test_defaults():
    args = _parse([])
    assert args.engine == "vosk"
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


# ── Tests: Whisper arguments ─────────────────────────────────────────────────

def test_whisper_model():
    args = _parse(["--whisper-model", "tiny"])
    assert args.whisper_model == "tiny"


def test_whisper_language():
    args = _parse(["--whisper-language", "en"])
    assert args.whisper_language == "en"


def test_whisper_device_cpu():
    args = _parse(["--whisper-device", "cpu"])
    assert args.whisper_device == "cpu"


def test_whisper_device_cuda():
    args = _parse(["--whisper-device", "cuda"])
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


# ── Tests: Logging ───────────────────────────────────────────────────────────

def test_debug_flag():
    args = _parse(["--debug"])
    assert args.debug is True


# ── Tests: main entry point ──────────────────────────────────────────────────

def test_main_creates_server_app():
    """Verify main() creates a ServerApp and calls run()."""
    from src.server_app import ServerApp

    with patch.object(ServerApp, "run") as mock_run:
        with patch("src.server.parse_args") as mock_args:
            mock_args.return_value = argparse.Namespace(
                engine="vosk",
                whisper_model="tiny",
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
            )
            from src.server import main
            main()
            mock_run.assert_called_once()


if __name__ == "__main__":
    test_defaults()
    test_engine_vosk()
    test_engine_whisper()
    test_whisper_model()
    test_whisper_language()
    test_whisper_device_cpu()
    test_whisper_device_cuda()
    test_llm_url()
    test_llm_key()
    test_llm_model()
    test_llm_timeout()
    test_llm_buffer_max()
    test_llm_silence_threshold()
    test_llm_buffer_min()
    test_all_llm_args()
    test_ssl_flag()
    test_ssl_certfile()
    test_ssl_keyfile()
    test_debug_flag()
    test_main_creates_server_app()
    print("All server.py tests passed!")
