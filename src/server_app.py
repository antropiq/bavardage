"""ServerApp: orchestrates aiohttp application, routes, and heartbeat checker."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web

from .llm_post_processor import LLMPostProcessor
from .vosk_engine import VoskEngine
from .session_manager import SessionManager

log = logging.getLogger(__name__)

PORT = 8765
STATIC_DIR = Path(__file__).parent / "static"
HEARTBEAT_TIMEOUT = 30  # seconds without ping before server shuts down
RESET_INTERVAL = 45.0  # seconds — reset Vosk internal state
PARTIAL_WORD_HISTORY = 5  # trailing words for partial dedup


class ServerApp:
    """Orchestrates the aiohttp server, routes, and global heartbeat management."""

    def __init__(
        self,
        engine=None,
        llm_processor: LLMPostProcessor | None = None,
        buffer_config: dict | None = None,
    ) -> None:
        from .vosk_engine import VoskEngine
        self._engine = engine or VoskEngine()
        self._llm_processor = llm_processor
        self._buffer_config = buffer_config or {}
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._shutdown_event = asyncio.Event()
        self._activity_task: asyncio.Task | None = None
        self._connected_clients = 0
        self._last_activity: float | None = None

    @property
    def engine(self) -> VoskEngine:
        return self._engine

    @property
    def connected_clients(self) -> int:
        return self._connected_clients

    def build_app(self) -> web.Application:
        """Build and configure the aiohttp application."""
        # Load model eagerly so health endpoint works
        self._engine.load()

        self._app = web.Application()
        self._app.router.add_get("/", self._index_handler)
        self._app.router.add_get("/style.css", self._css_handler)
        self._app.router.add_get("/app.js", self._js_handler)
        self._app.router.add_get("/audio-processor.js", self._js_handler)
        self._app.router.add_get("/health", self._health_handler)
        self._app.router.add_get("/ws", self._websocket_handler)
        return self._app

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection — stream audio → Vosk → stream text."""
        ws = web.WebSocketResponse(compress=True)
        await ws.prepare(request)
        log.info("Client connected")

        # Send ready signal before accepting audio
        await ws.send_json({"type": "ready"})

        # Track session
        self._connected_clients += 1
        self._update_activity()
        self._ensure_heartbeat_checker()

        session = SessionManager(
            engine=self._engine,
            reset_interval=RESET_INTERVAL,
            partial_word_history=PARTIAL_WORD_HISTORY,
            llm_processor=self._llm_processor,
            buffer_config=self._buffer_config,
        )
        await session._setup()

        chunk_count = 0
        try:
            async for msg in ws:
                self._update_activity()
                now = asyncio.get_event_loop().time()
                await session.handle_message(msg, ws, now)
                chunk_count = session.chunk_count

            log.info("Stream ended after %d chunks", chunk_count)
        except Exception as exc:
            log.exception("WebSocket error after %d chunks: %s", chunk_count, exc)
        finally:
            await session.close()
            self._connected_clients -= 1
            log.info("Client disconnected (%d clients remaining)", self._connected_clients)

        return ws

    async def _health_handler(self, request: web.Request) -> web.Response:
        """Health check — returns 200 only when model is loaded."""
        status = self._engine.get_health_status()
        status_code = 200 if status["status"] == "ready" else 202
        return web.json_response(status, status=status_code)

    def _static_file_handler(self, path: str) -> web.FileResponse:
        """Serve a static file, returning FileResponse or HTTP 404."""
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if not file_path.is_file() or not str(file_path).startswith(str(STATIC_DIR.resolve())):
            return web.Response(status=404, text="Not found")
        return web.FileResponse(file_path)

    async def _index_handler(self, request: web.Request) -> web.FileResponse:
        return self._static_file_handler("/index.html")

    async def _css_handler(self, request: web.Request) -> web.FileResponse:
        return self._static_file_handler(request.path)

    async def _js_handler(self, request: web.Request) -> web.FileResponse:
        return self._static_file_handler(request.path)

    def _update_activity(self) -> None:
        """Record the last time we received activity from a client."""
        self._last_activity = asyncio.get_event_loop().time()

    def _ensure_heartbeat_checker(self) -> None:
        """Ensure a single heartbeat checker task is running."""
        if self._activity_task is None or self._activity_task.done():
            self._activity_task = asyncio.create_task(self._heartbeat_checker())

    async def _heartbeat_checker(self) -> None:
        """Periodically check if we've heard from any client within the timeout."""
        while True:
            try:
                await asyncio.wait_for(asyncio.sleep(5), timeout=5)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break

            if self._connected_clients == 0 and self._last_activity is not None:
                now = asyncio.get_event_loop().time()
                if (now - self._last_activity) > HEARTBEAT_TIMEOUT:
                    log.warning("No client activity for %d seconds — shutting down server", HEARTBEAT_TIMEOUT)
                    self._shutdown_event.set()
                    break

    async def start(self) -> None:
        """Start the aiohttp server and wait for shutdown."""
        if self._app is None:
            self.build_app()

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", PORT)
        log.info("Server running on http://0.0.0.0:%d", PORT)

        try:
            await site.start()
            log.info("Waiting for client activity (timeout: %ds)...", HEARTBEAT_TIMEOUT)
            try:
                await self._shutdown_event.wait()
            except KeyboardInterrupt:
                pass
        except KeyboardInterrupt:
            pass

    async def stop(self) -> None:
        """Gracefully shut down the server."""
        log.info("Shutting down server…")
        self._shutdown_event.set()

        # Cancel all remaining tasks to prevent zombie processes
        loop = asyncio.get_event_loop()
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
        # Use create_task + sleep instead of run_until_complete to avoid
        # "event loop is already running" during KeyboardInterrupt
        if pending:
            gather = loop.create_task(asyncio.gather(*pending, return_exceptions=True))
            try:
                await gather
            except (asyncio.CancelledError, RuntimeError):
                pass

        # Cleanup aiohttp
        if self._runner:
            try:
                await self._runner.cleanup()
            except (asyncio.CancelledError, RuntimeError):
                pass

    @classmethod
    def from_args(cls, args) -> "ServerApp":
        """Create ServerApp from parsed CLI arguments."""
        from .vosk_engine import VoskEngine, MODEL_PATH

        engine = VoskEngine(model_path=MODEL_PATH)

        llm_processor = None
        if getattr(args, "llm_url", None):
            llm_processor = LLMPostProcessor(
                api_url=args.llm_url,
                api_key=getattr(args, "llm_key", None),
                model=getattr(args, "llm_model", "llama3"),
                timeout=getattr(args, "llm_timeout", 5.0),
            )

        buffer_config = {
            "max_buffer_size": getattr(args, "llm_buffer_max", 500),
            "silence_threshold": getattr(args, "llm_silence_threshold", 2.0),
            "min_buffer_size": getattr(args, "llm_buffer_min", 20),
        }

        return cls(
            engine=engine,
            llm_processor=llm_processor,
            buffer_config=buffer_config,
        )

    def run(self) -> None:
        """Synchronous entry point: start, run, stop."""
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            # During KeyboardInterrupt the loop is still running, so we
            # cancel tasks directly instead of re-entering run_until_complete.
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            # Signal shutdown so the heartbeat checker exits its loop
            self._shutdown_event.set()
        finally:
            # Force cleanup: close runner's TCP site if still open
            if self._runner:
                try:
                    loop.run_until_complete(self._runner.cleanup())
                except (asyncio.CancelledError, RuntimeError):
                    pass
            # Clear global resources
            self._engine._model = None
            self._engine._loaded = False
