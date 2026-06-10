from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from aiohttp import web
from vosk import KaldiRecognizer, Model

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

PORT = 8765
PROJECT_ROOT = Path(__file__).parent.parent
MODEL_PATH = PROJECT_ROOT / "vosk-model-small-fr-0.22"
STATIC_DIR = Path(__file__).parent / "static"

_model: Model | None = None
_model_loaded: asyncio.Event | None = None
_last_activity: float | None = None
_activity_task: asyncio.Task | None = None
_runner: web.AppRunner | None = None
_shutdown_event: asyncio.Event | None = None
HEARTBEAT_TIMEOUT = 30  # seconds without ping before server shuts down


def _get_model() -> Model:
    global _model
    if _model is None:
        if not MODEL_PATH.is_dir():
            log.error("Vosk model not found at %s", MODEL_PATH)
            sys.exit(1)
        log.info("Loading Vosk model from %s (this may take a moment)...", MODEL_PATH)
        _model = Model(str(MODEL_PATH))
        log.info("Vosk model loaded.")
        if _model_loaded:
            _model_loaded.set()
    return _model


def _update_activity():
    """Record the last time we received activity from a client."""
    global _last_activity
    _last_activity = asyncio.get_event_loop().time()


async def _heartbeat_checker() -> None:
    """Periodically check if we've heard from any client within the timeout."""
    global _activity_task
    while True:
        # Wait 5s or until shutdown is requested, whichever comes first
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=5)
            # Shutdown event was set — exit loop
            break
        except asyncio.TimeoutError:
            pass

        now = asyncio.get_event_loop().time()
        if _last_activity is not None and (now - _last_activity) > HEARTBEAT_TIMEOUT:
            log.warning("No client activity for %d seconds — shutting down server", HEARTBEAT_TIMEOUT)
            _shutdown_event.set()
            break


def _get_runner() -> web.AppRunner | None:
    return _runner


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connection — stream audio → Vosk → stream text."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    log.info("Client connected")

    # Send ready signal before accepting audio
    await ws.send_json({"type": "ready"})

    recognizer = KaldiRecognizer(_get_model(), 16000)
    recognizer.SetWords(True)
    chunk_count = 0

    # Start heartbeat checker
    _update_activity()
    _activity_task = asyncio.create_task(_heartbeat_checker())

    try:
        async for msg in ws:
            _update_activity()

            if msg.type == web.WSMsgType.TEXT:
                data = msg.data.encode("utf-8")
                # Handle ping from client
                if msg.data == "ping":
                    await ws.send_str("pong")
                    continue
            elif msg.type == web.WSMsgType.BINARY:
                data = msg.data
            elif msg.type == web.WSMsgType.CLOSED:
                break
            else:
                continue

            if not data or len(data) == 0:
                break

            chunk_count += 1

            accepted = recognizer.AcceptWaveform(data)

            if accepted:
                result_str = recognizer.FinalResult()
                try:
                    result = json.loads(result_str)
                except json.JSONDecodeError:
                    log.warning("Bad FinalResult JSON: %r", result_str[:200])
                    continue

                text = result.get("text", "").strip()
                if text:
                    log.info("FINAL [%d]: %s", chunk_count, text)
                    await ws.send_json({"type": "final", "text": text})
            else:
                partial_str = recognizer.PartialResult()
                try:
                    partial = json.loads(partial_str)
                except json.JSONDecodeError:
                    continue

                text = partial.get("partial", "").strip()
                if text:
                    await ws.send_json({"type": "partial", "text": text})

        log.info("Stream ended after %d chunks", chunk_count)
    except Exception as exc:
        log.exception("WebSocket error after %d chunks: %s", chunk_count, exc)
    finally:
        log.info("Client disconnected")
        if _activity_task and not _activity_task.done():
            _activity_task.cancel()
            try:
                await _activity_task
            except asyncio.CancelledError:
                pass
        # Signal the main loop to shut down
        if _shutdown_event and not _shutdown_event.is_set():
            _shutdown_event.set()

    return ws


async def health_handler(request: web.Request) -> web.Response:
    """Health check — returns 200 only when model is loaded."""
    if _model is not None:
        return web.json_response({"status": "ready"})
    return web.json_response({"status": "loading"}, status=202)


def _static_file_handler(path: str) -> web.FileResponse:
    """Serve a static file, returning FileResponse or HTTP 404."""
    file_path = (STATIC_DIR / path.lstrip("/")).resolve()
    if not file_path.is_file() or not str(file_path).startswith(str(STATIC_DIR.resolve())):
        return web.Response(status=404, text="Not found")
    return web.FileResponse(file_path)


async def index_handler(request: web.Request) -> web.FileResponse:
    return _static_file_handler("/index.html")


async def css_handler(request: web.Request) -> web.FileResponse:
    return _static_file_handler(request.path)


async def js_handler(request: web.Request) -> web.FileResponse:
    return _static_file_handler(request.path)


def build_app() -> web.Application:
    global _model_loaded
    _model_loaded = asyncio.Event()

    # Load model eagerly so the health endpoint works
    _get_model()

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/style.css", css_handler)
    app.router.add_get("/app.js", js_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/ws", websocket_handler)
    return app


def main() -> None:
    app = build_app()
    global _runner, _shutdown_event
    _runner = web.AppRunner(app)
    asyncio.get_event_loop().run_until_complete(_runner.setup())
    _shutdown_event = asyncio.Event()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    log.info("Server running on http://0.0.0.0:%d", PORT)
    try:
        asyncio.get_event_loop().run_until_complete(site.start())
        log.info("Waiting for client activity (timeout: %ds)...", HEARTBEAT_TIMEOUT)
        try:
            asyncio.get_event_loop().run_until_complete(_shutdown_event.wait())
        except KeyboardInterrupt:
            pass
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Shutting down server…")
        asyncio.get_event_loop().run_until_complete(_runner.cleanup())


if __name__ == "__main__":
    main()
