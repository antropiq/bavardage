"""Unit tests for ServerApp."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server_app import ServerApp


def make_mock_engine(**kwargs):
    engine = MagicMock()
    engine.is_loaded = kwargs.get("is_loaded", True)
    engine.load = MagicMock()
    engine.create_recognizer = AsyncMock(return_value=MagicMock())
    engine.return_recognizer = AsyncMock()
    engine.parse_final_result = MagicMock(return_value={"text": "test"})
    engine.parse_partial_result = MagicMock(return_value={"partial": "test"})
    engine.get_health_status = MagicMock(return_value={"status": "ready"})
    return engine


def make_mock_args(**kwargs):
    defaults = {
        "engine": "vosk",
        "whisper_model": "tiny",
        "whisper_language": "fr",
        "whisper_device": "auto",
        "llm_url": None,
        "llm_key": None,
        "llm_model": "llama3",
        "llm_timeout": 15.0,
        "llm_buffer_max": 500,
        "llm_silence_threshold": 2.0,
        "llm_buffer_min": 20,
        "ssl": False,
        "ssl_certfile": None,
        "ssl_keyfile": None,
        "debug": False,
    }
    defaults.update(kwargs)
    return MagicMock(**defaults)


# ── Test 1: Initialization ──────────────────────────────────────────────────

def test_init_default_engine():
    app = ServerApp()
    assert app.engine is not None


# ── Test 2: build_app ────────────────────────────────────────────────────────

def test_build_app_creates_application():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    result = app.build_app()
    assert result is not None
    assert app._app is result


# ── Test 3: build_app calls engine.load ──────────────────────────────────────

def test_build_app_calls_engine_load():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    engine.load.assert_called_once()


# ── Test 4: health handler ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_ready():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._health_handler(MagicMock())
    assert response.status == 200
    body = json.loads(response.text)
    assert body["status"] == "ready"


# ── Test 5: health loading ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_loading():
    engine = make_mock_engine()
    engine.get_health_status.return_value = {"status": "loading"}
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._health_handler(MagicMock())
    assert response.status == 202


# ── Test 6: from_args default ───────────────────────────────────────────────

def test_from_args_vosk_default():
    app = ServerApp.from_args(make_mock_args())
    assert app._llm_processor is None


# ── Test 7: from_args with LLM ──────────────────────────────────────────────

def test_from_args_with_llm():
    args = make_mock_args(llm_url="http://localhost:8080", llm_key="secret")
    app = ServerApp.from_args(args)
    assert app._llm_processor is not None
    assert app._llm_processor._api_url == "http://localhost:8080"
    assert app._llm_processor._api_key == "secret"


# ── Test 8: from_args SSL disabled ──────────────────────────────────────────

def test_from_args_ssl_disabled():
    app = ServerApp.from_args(make_mock_args(ssl=False))
    assert app._ssl_context is None


# ── Test 9: from_args SSL enabled ───────────────────────────────────────────

def test_from_args_ssl_enabled():
    args = make_mock_args(ssl=True)
    with patch("src.server_app._create_ssl_context") as mock_ssl:
        mock_ssl.return_value = MagicMock()
        app = ServerApp.from_args(args)
        mock_ssl.assert_called_once_with(args)
        assert app._ssl_context is not None


# ── Test 10: static route serves files ──────────────────────────────────────

@pytest.mark.asyncio
async def test_static_route_serves_files():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    # Simulate a request to /static/style.css
    request = MagicMock()
    request.path = "/static/style.css"
    # Verify the static route is registered by checking the router
    routes = [r for r in app._app.router.routes()]
    static_routes = [r for r in routes if hasattr(r, 'resource') and r.resource and 'static' in str(r.resource)]
    assert len(static_routes) >= 1


# ── Test 11: index handler returns file ──────────────────────────────────────

@pytest.mark.asyncio
async def test_index_handler_returns_file():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._index_handler(MagicMock())
    assert response.status == 200


# ── Test 12: LLM chat not configured ────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_chat_not_configured():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(return_value={"text": "hello"})
    response = await app._llm_chat_handler(request)
    assert response.status == 503


# ── Test 13: LLM chat success ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_chat_success():
    llm = MagicMock()
    llm.enabled = True
    llm._call_llm = AsyncMock(return_value={"choices": [{"message": {"content": "Reponse"}}]})
    llm._extract_text = MagicMock(return_value="Reponse")
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(return_value={"text": "Bonjour"})
    response = await app._llm_chat_handler(request)
    assert response.status == 200
    body = json.loads(response.text)
    assert "answer" in body


# ── Test 14: stop cleans runner ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_cleans_runner():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    app._runner = MagicMock()
    app._runner.cleanup = AsyncMock()
    await app.stop()
    app._runner.cleanup.assert_called_once()


# ── Test 16: run catches KeyboardInterrupt ──────────────────────────────────

def test_run_catches_keyboard_interrupt():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop_instance = MagicMock()
        mock_loop.return_value = mock_loop_instance
        mock_loop_instance.run_until_complete.side_effect = KeyboardInterrupt()
        app.run()


# ── Test 17: run cleans up engine ───────────────────────────────────────────

def test_run_cleanup_engine():
    engine = make_mock_engine()
    engine._model = MagicMock()
    engine._loaded = True
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop_instance = MagicMock()
        mock_loop.return_value = mock_loop_instance
        mock_loop_instance.run_until_complete.side_effect = KeyboardInterrupt()
        app.run()
        assert engine._model is None
        assert engine._loaded is False


if __name__ == "__main__":
    test_init_default_engine()
    test_build_app_creates_application()
    test_build_app_calls_engine_load()
    test_from_args_vosk_default()
    test_from_args_with_llm()
    test_from_args_ssl_disabled()
    test_from_args_ssl_enabled()
    print("All sync tests passed!")
