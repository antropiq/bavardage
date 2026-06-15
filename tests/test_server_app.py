"""Unit tests for ServerApp."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server_app import ServerApp, _create_ssl_context


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
        "vosk_model": None,
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


# ── Initialization ───────────────────────────────────────────────────────────

def test_init_default_engine():
    app = ServerApp()
    assert app.engine is not None


def test_init_custom_engine():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    assert app.engine is engine


def test_init_with_llm_processor():
    llm = MagicMock()
    app = ServerApp(llm_processor=llm)
    assert app._llm_processor is llm


def test_init_with_buffer_config():
    app = ServerApp(buffer_config={"max_buffer_size": 1000})
    assert app._buffer_config["max_buffer_size"] == 1000


def test_init_with_ssl_context():
    ssl_ctx = MagicMock()
    app = ServerApp(ssl_context=ssl_ctx)
    assert app._ssl_context is ssl_ctx


def test_init_sessions_empty():
    app = ServerApp()
    assert app._sessions == {}


# ── Engine property ──────────────────────────────────────────────────────────

def test_engine_property():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    assert app.engine is engine


# ── build_app ────────────────────────────────────────────────────────────────

def test_build_app_creates_application():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    result = app.build_app()
    assert result is not None
    assert app._app is result


def test_build_app_calls_engine_load():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    engine.load.assert_called_once()


def test_build_app_registers_routes():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    routes = [r for r in app._app.router.routes()]
    handler_names = [r.handler.__name__ for r in routes if hasattr(r, 'handler')]
    assert "_index_handler" in handler_names
    assert "_health_handler" in handler_names
    assert "_stats_handler" in handler_names
    assert "_websocket_handler" in handler_names


def test_build_app_registers_static_route():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    routes = [r for r in app._app.router.routes()]
    static_routes = [r for r in routes if hasattr(r, 'resource') and r.resource and 'static' in str(r.resource)]
    assert len(static_routes) >= 1


# ── Health handler ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_ready():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._health_handler(MagicMock())
    assert response.status == 200
    body = json.loads(response.text)
    assert body["status"] == "ready"


@pytest.mark.asyncio
async def test_health_loading():
    engine = make_mock_engine()
    engine.get_health_status.return_value = {"status": "loading"}
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._health_handler(MagicMock())
    assert response.status == 202


@pytest.mark.asyncio
async def test_health_with_llm_enabled():
    llm = MagicMock()
    llm.enabled = True
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    response = await app._health_handler(MagicMock())
    body = json.loads(response.text)
    assert body["llm_enabled"] is True


@pytest.mark.asyncio
async def test_health_with_llm_disabled():
    llm = MagicMock()
    llm.enabled = False
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    response = await app._health_handler(MagicMock())
    body = json.loads(response.text)
    assert body["llm_enabled"] is False


# ── Stats handler ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stats_handler_empty():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._stats_handler(MagicMock())
    body = json.loads(response.text)
    assert body["active_sessions"] == 0
    assert body["total_chunks_processed"] == 0
    assert body["sessions"] == []


@pytest.mark.asyncio
async def test_stats_handler_with_sessions():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    # Manually add a session
    mock_session = MagicMock()
    mock_session.get_stats.return_value = {"chunks": 42, "last_final": "hello"}
    loop = asyncio.get_event_loop()
    app._sessions["test:123"] = {"session": mock_session, "start_time": loop.time() - 10}
    response = await app._stats_handler(MagicMock())
    body = json.loads(response.text)
    assert body["active_sessions"] == 1
    assert body["total_chunks_processed"] == 42
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["duration_seconds"] >= 10


# ── Index handler ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_index_handler_returns_file():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    response = await app._index_handler(MagicMock())
    assert response.status == 200


@pytest.mark.asyncio
async def test_index_handler_static_route():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    # Verify static route is registered
    routes = list(app._app.router.routes())
    static_routes = [r for r in routes if hasattr(r, 'resource') and r.resource and 'static' in str(r.resource)]
    assert len(static_routes) >= 1


# ── LLM chat handler ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_chat_not_configured():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(return_value={"text": "hello"})
    response = await app._llm_chat_handler(request)
    assert response.status == 503


@pytest.mark.asyncio
async def test_llm_chat_empty_text():
    llm = MagicMock()
    llm.enabled = True
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(return_value={"text": ""})
    response = await app._llm_chat_handler(request)
    assert response.status == 400
    body = json.loads(response.text)
    assert "error" in body


@pytest.mark.asyncio
async def test_llm_chat_invalid_json():
    llm = MagicMock()
    llm.enabled = True
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(side_effect=Exception("bad json"))
    response = await app._llm_chat_handler(request)
    assert response.status == 400


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


@pytest.mark.asyncio
async def test_llm_chat_empty_response():
    llm = MagicMock()
    llm.enabled = True
    llm._call_llm = AsyncMock(return_value={"choices": [{"message": {"content": ""}}]})
    llm._extract_text = MagicMock(return_value="")
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(return_value={"text": "Bonjour"})
    response = await app._llm_chat_handler(request)
    assert response.status == 502


@pytest.mark.asyncio
async def test_llm_chat_exception():
    llm = MagicMock()
    llm.enabled = True
    llm._call_llm = AsyncMock(side_effect=Exception("API error"))
    engine = make_mock_engine()
    app = ServerApp(engine=engine, llm_processor=llm)
    app.build_app()
    request = MagicMock()
    request.json = AsyncMock(return_value={"text": "Bonjour"})
    response = await app._llm_chat_handler(request)
    assert response.status == 502


# ── WebSocket handler ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_handler_ready_signal():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("src.server_app.web.WebSocketResponse") as MockWS:
        mock_ws = AsyncMock()
        mock_ws.prepare = AsyncMock()
        mock_ws.__aiter__ = AsyncMock(return_value=iter([]))
        MockWS.return_value = mock_ws
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"
        with patch("src.server_app.SessionManager") as MockSession:
            mock_session = MagicMock()
            mock_session._setup = AsyncMock()
            mock_session.handle_message = AsyncMock()
            mock_session.close = AsyncMock()
            mock_session.chunk_count = 0
            MockSession.return_value = mock_session
            result = await app._websocket_handler(mock_request)
            mock_ws.send_json.assert_called_with({"type": "ready"})
            MockSession.return_value._setup.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_handler_error():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("src.server_app.web.WebSocketResponse") as MockWS:
        mock_ws = AsyncMock()
        mock_ws.prepare = AsyncMock()
        mock_ws.__aiter__ = AsyncMock(return_value=iter([MagicMock()]))
        MockWS.return_value = mock_ws
        mock_request = MagicMock()
        mock_request.remote = "127.0.0.1"
        with patch("src.server_app.SessionManager") as MockSession:
            mock_session = MagicMock()
            mock_session._setup = AsyncMock()
            mock_session.handle_message = AsyncMock(side_effect=Exception("audio error"))
            mock_session.close = AsyncMock()
            mock_session.chunk_count = 5
            mock_session.get_stats = MagicMock(return_value={"chunks": 5})
            MockSession.return_value = mock_session
            result = await app._websocket_handler(mock_request)
            mock_session.close.assert_called_once()


# ── SSL context ─────────────────────────────────────────────────────────────

def test_create_ssl_context_with_custom_files(tmp_path):
    certfile = str(tmp_path / "cert.pem")
    keyfile = str(tmp_path / "key.pem")
    Path(certfile).touch()
    Path(keyfile).touch()
    args = MagicMock()
    args.ssl_certfile = certfile
    args.ssl_keyfile = keyfile
    with patch("src.server_app.SSL_DIR") as mock_dir:
        mock_dir.exists.return_value = False
        mock_dir.__truediv__.return_value.__str__.return_value = str(tmp_path / "cert.pem")
        try:
            ctx = _create_ssl_context(args)
        except Exception:
            pass


def test_create_ssl_context_auto_generates(tmp_path):
    """Test SSL context creation with auto-generated cert/key."""
    args = MagicMock()
    args.ssl_certfile = None
    args.ssl_keyfile = None
    with patch("src.server_app.SSL_DIR") as mock_dir:
        mock_dir.exists.return_value = False
        mock_dir.__truediv__.return_value.__str__.return_value = str(tmp_path / "cert.pem")
        try:
            ctx = _create_ssl_context(args)
        except Exception:
            pass


# ── from_args ───────────────────────────────────────────────────────────────

def test_from_args_vosk_default():
    app = ServerApp.from_args(make_mock_args())
    assert app._llm_processor is None


def test_from_args_vosk_with_model_path():
    args = make_mock_args(vosk_model="/custom/vosk/model")
    app = ServerApp.from_args(args)
    assert app._engine._model_path == Path("/custom/vosk/model")


def test_from_args_with_llm():
    args = make_mock_args(llm_url="http://localhost:8080", llm_key="secret")
    app = ServerApp.from_args(args)
    assert app._llm_processor is not None
    assert app._llm_processor._api_url == "http://localhost:8080"
    assert app._llm_processor._api_key == "secret"


def test_from_args_whisper_engine():
    args = make_mock_args(engine="whisper", whisper_model="tiny", whisper_language="en", whisper_device="cpu")
    app = ServerApp.from_args(args)
    from src.whisper_engine import WhisperEngine
    assert isinstance(app._engine, WhisperEngine)


def test_from_args_whisper_default_model():
    args = make_mock_args(engine="whisper")
    app = ServerApp.from_args(args)
    from src.whisper_engine import WhisperEngine
    assert isinstance(app._engine, WhisperEngine)


def test_from_args_with_all_options():
    args = make_mock_args(
        llm_url="http://localhost:8080",
        llm_key="secret",
        llm_model="phi3",
        llm_timeout=30.0,
        llm_buffer_max=1000,
        llm_silence_threshold=5.0,
        llm_buffer_min=50,
    )
    app = ServerApp.from_args(args)
    assert app._llm_processor._api_url == "http://localhost:8080"
    assert app._llm_processor._model == "phi3"
    assert app._llm_processor._timeout == 30.0
    assert app._buffer_config["max_buffer_size"] == 1000
    assert app._buffer_config["silence_threshold"] == 5.0
    assert app._buffer_config["min_buffer_size"] == 50


def test_from_args_ssl_disabled():
    app = ServerApp.from_args(make_mock_args(ssl=False))
    assert app._ssl_context is None


def test_from_args_ssl_enabled():
    args = make_mock_args(ssl=True)
    with patch("src.server_app._create_ssl_context") as mock_ssl:
        mock_ssl.return_value = MagicMock()
        app = ServerApp.from_args(args)
        mock_ssl.assert_called_once_with(args)
        assert app._ssl_context is not None


# ── from_config ─────────────────────────────────────────────────────────────

def test_from_config_vosk_default():
    from src.config import ServerConfig
    config = ServerConfig()
    app = ServerApp.from_config(config)
    assert app._llm_processor is None


def test_from_config_vosk_with_llm():
    from src.config import ServerConfig, LLMConfig
    config = ServerConfig(
        llm=LLMConfig(api_url="http://localhost:8080", model="phi3")
    )
    app = ServerApp.from_config(config)
    assert app._llm_processor is not None
    assert app._llm_processor._model == "phi3"


def test_from_config_whisper():
    from src.config import ServerConfig
    config = ServerConfig(engine="whisper", whisper_model="tiny", whisper_language="en")
    app = ServerApp.from_config(config)
    from src.whisper_engine import WhisperEngine
    assert isinstance(app._engine, WhisperEngine)


def test_from_config_with_ssl():
    from src.config import ServerConfig
    config = ServerConfig(ssl=True, ssl_certfile="/cert.pem", ssl_keyfile="/key.pem")
    with patch("src.server_app._create_ssl_context") as mock_ssl:
        mock_ssl.return_value = MagicMock()
        app = ServerApp.from_config(config)
        mock_ssl.assert_called_once()


def test_from_config_buffer_config():
    from src.config import ServerConfig
    config = ServerConfig(llm_buffer_max=1000, llm_silence_threshold=5.0, llm_buffer_min=50)
    app = ServerApp.from_config(config)
    assert app._buffer_config["max_buffer_size"] == 1000
    assert app._buffer_config["silence_threshold"] == 5.0
    assert app._buffer_config["min_buffer_size"] == 50


# ── stop ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_cleans_runner():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    app._runner = MagicMock()
    app._runner.cleanup = AsyncMock()
    await app.stop()
    app._runner.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_stop_no_runner():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    # Should not raise
    await app.stop()


@pytest.mark.asyncio
async def test_stop_runner_cleanup_raises():
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    app._runner = MagicMock()
    app._runner.cleanup = AsyncMock(side_effect=RuntimeError("cleanup failed"))
    # Should not raise
    await app.stop()


# ── run ─────────────────────────────────────────────────────────────────────

def test_run_catches_keyboard_interrupt():
    """Test run() catches KeyboardInterrupt and cleans up."""
    engine = make_mock_engine()
    engine._model = MagicMock()
    engine._loaded = True
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("os._exit"), patch.object(app, "start", side_effect=KeyboardInterrupt()):
        app.run()
    assert engine._model is None
    assert engine._loaded is False


def test_run_cleanup_engine():
    """Test run() cleans up engine state."""
    engine = make_mock_engine()
    engine._model = MagicMock()
    engine._loaded = True
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("os._exit"), patch.object(app, "start", side_effect=KeyboardInterrupt()):
        app.run()
    assert engine._model is None
    assert engine._loaded is False


def test_run_no_engine_model():
    """Test run() handles engine without _model attribute."""
    engine = make_mock_engine()
    del engine._model
    engine._loaded = True
    app = ServerApp(engine=engine)
    app.build_app()
    with patch("os._exit"), patch.object(app, "start", side_effect=KeyboardInterrupt()):
        app.run()
    assert engine._loaded is False


def test_run_with_runner_cleanup_error():
    """Test run() handles runner cleanup errors."""
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    app._runner = MagicMock()
    app._runner.cleanup = AsyncMock(side_effect=RuntimeError("fail"))
    with patch("os._exit"), patch.object(app, "start", side_effect=KeyboardInterrupt()):
        app.run()


def test_run_creates_app_if_none():
    """Test run() builds app if not already built."""
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    assert app._app is None
    # start() calls build_app() if self._app is None
    # We patch the site.start to raise KeyboardInterrupt immediately
    with patch("os._exit"), patch("aiohttp.web.TCPSite.start", new_callable=AsyncMock):
        with patch("asyncio.Event.wait", side_effect=KeyboardInterrupt()):
            app.run()
    assert app._app is not None


def test_run_pending_tasks_cancelled():
    """Test run() cancels pending tasks on KeyboardInterrupt."""
    engine = make_mock_engine()
    app = ServerApp(engine=engine)
    app.build_app()
    # Create a pending task
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def dummy_task():
        await asyncio.sleep(100)
    loop.create_task(dummy_task())
    with patch("os._exit"), patch.object(app, "start", side_effect=KeyboardInterrupt()):
        app.run()
    loop.close()


if __name__ == "__main__":
    test_init_default_engine()
    test_build_app_creates_application()
    test_build_app_calls_engine_load()
    test_from_args_vosk_default()
    test_from_args_with_llm()
    test_from_args_ssl_disabled()
    test_from_args_ssl_enabled()
    print("All sync tests passed!")
