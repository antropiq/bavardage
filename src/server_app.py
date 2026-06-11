"""ServerApp: orchestrates aiohttp application, routes, and WebSocket sessions."""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import logging
import ssl
from pathlib import Path

from aiohttp import web

from .base_engine import BaseEngine
from .llm_post_processor import LLMPostProcessor
from .session_manager import SessionManager

log = logging.getLogger(__name__)

PORT = 8765
STATIC_DIR = Path(__file__).parent / "static"
RESET_INTERVAL = 45.0  # seconds — reset Vosk internal state
PARTIAL_WORD_HISTORY = 5  # trailing words for partial dedup
SSL_DIR = Path.home() / ".realtime-speech" / ".ssl"


def _create_ssl_context(args) -> ssl.SSLContext:
    """Create an SSL context, generating a self-signed cert if needed."""
    certfile = args.ssl_certfile
    keyfile = args.ssl_keyfile

    if not certfile or not keyfile:
        SSL_DIR.mkdir(parents=True, exist_ok=True)
        default_cert = SSL_DIR / "cert.pem"
        default_key = SSL_DIR / "key.pem"
        if not certfile and not default_cert.exists():
            default_cert.touch()
        if not keyfile and not default_key.exists():
            default_key.touch()
        certfile = certfile or str(default_cert)
        keyfile = keyfile or str(default_key)

    log.info("Generating self-signed SSL certificate...")
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    except ImportError:
        log.error("cryptography package required for --ssl. Install it: pip install cryptography")
        raise

    # Generate private key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = Path(keyfile)
    key_path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()))

    # Generate certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Localhost"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Realtime Speech"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.DNSName("*.localhost"),
            x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            x509.IPAddress(ipaddress.IPv4Address("0.0.0.0")),
        ]), critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = Path(certfile)
    cert_path.write_bytes(cert.public_bytes(Encoding.PEM))

    log.info("SSL certificate generated at %s", certfile)

    # Load and return SSL context
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile, keyfile)
    return ctx


class ServerApp:
    """Orchestrates the aiohttp server, routes, and WebSocket session management."""

    def __init__(
        self,
        engine=None,
        llm_processor: LLMPostProcessor | None = None,
        buffer_config: dict | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        from .vosk_engine import VoskEngine
        self._engine = engine or VoskEngine()
        self._llm_processor = llm_processor
        self._buffer_config = buffer_config or {}
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._ssl_context = ssl_context

    @property
    def engine(self) -> BaseEngine:
        return self._engine

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
        self._app.router.add_post("/api/llm-chat", self._llm_chat_handler)
        self._app.router.add_get("/ws", self._websocket_handler)
        return self._app

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection — stream audio → Vosk → stream text."""
        ws = web.WebSocketResponse(compress=True)
        await ws.prepare(request)
        client_ip = request.remote or "unknown"
        log.info("Client connected from %s", client_ip)

        # Send ready signal before accepting audio
        await ws.send_json({"type": "ready"})

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
                now = asyncio.get_event_loop().time()
                await session.handle_message(msg, ws, now)
                chunk_count = session.chunk_count

            log.debug("Stream ended after %d chunks", chunk_count)
        except Exception as exc:
            log.exception("WebSocket error after %d chunks: %s", chunk_count, exc)
        finally:
            await session.close()
            log.info("Client disconnected")

        return ws

    async def _llm_chat_handler(self, request: web.Request) -> web.Response:
        """Handle LLM chat queries — send user text and get LLM response."""
        if not self._llm_processor or not self._llm_processor.enabled:
            return web.json_response({"error": "LLM not configured"}, status=503)

        try:
            body = await request.json()
            user_text = body.get("text", "").strip()
            if not user_text:
                return web.json_response({"error": "Empty text"}, status=400)
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        try:
            chat_system_prompt = (
                "You are a helpful French assistant. The user will send you transcribed speech text. "
                "Respond naturally to it as if you are continuing the conversation. "
                "If it is a question, answer it. If it is a statement, acknowledge it and add relevant information. "
                "Always respond in French. Be concise."
            )
            log.info("LLM chat: url=%s model=%s text=%s", self._llm_processor._api_url, self._llm_processor._model, user_text[:100])
            response = await self._llm_processor._call_llm(
                user_text, system_prompt=chat_system_prompt
            )
            answer = self._llm_processor._extract_text(response)
            if answer:
                return web.json_response({"answer": answer})
            return web.json_response({"error": "Empty response from LLM"}, status=502)
        except Exception as e:
            log.exception("LLM chat failed: %s", e)
            return web.json_response({"error": str(e)}, status=502)

    async def _health_handler(self, request: web.Request) -> web.Response:
        """Health check — returns 200 only when model is loaded."""
        status = self._engine.get_health_status()
        status_code = 200 if status["status"] == "ready" else 202
        response = {
            "status": status["status"],
            "llm_enabled": self._llm_processor is not None and self._llm_processor.enabled,
        }
        return web.json_response(response, status=status_code)

    def _static_file_handler(self, path: str) -> web.FileResponse:
        """Serve a static file, returning FileResponse or HTTP 404."""
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if not file_path.is_file() or not str(file_path).startswith(str(STATIC_DIR.resolve())):
            return web.Response(status=404, text="Not found")
        return web.FileResponse(file_path)

    async def _index_handler(self, request: web.Request) -> web.FileResponse:
        return self._static_file_handler("/index.html")

    async def _css_handler(self, request: web.Request) -> web.Response:
        file_path = (STATIC_DIR / request.path.lstrip("/")).resolve()
        if not file_path.is_file():
            return web.Response(status=404, text="Not found")
        resp = web.FileResponse(file_path)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    async def _js_handler(self, request: web.Request) -> web.Response:
        file_path = (STATIC_DIR / request.path.lstrip("/")).resolve()
        if not file_path.is_file():
            return web.Response(status=404, text="Not found")
        resp = web.FileResponse(file_path)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    async def start(self) -> None:
        """Start the aiohttp server and wait for shutdown (Ctrl+C only)."""
        if self._app is None:
            self.build_app()

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        if self._ssl_context:
            site = web.TCPSite(self._runner, "0.0.0.0", PORT, ssl_context=self._ssl_context)
            scheme = "https"
        else:
            site = web.TCPSite(self._runner, "0.0.0.0", PORT)
            scheme = "http"

        log.info("Server running on %s://0.0.0.0:%d", scheme, PORT)
        log.info("Server will run until stopped with Ctrl+C")

        try:
            await site.start()
            await asyncio.Event().wait()  # Wait forever until KeyboardInterrupt
        except KeyboardInterrupt:
            pass

    async def stop(self) -> None:
        """Gracefully shut down the server."""
        log.info("Shutting down server…")

        # Cleanup aiohttp
        if self._runner:
            try:
                await self._runner.cleanup()
            except (asyncio.CancelledError, RuntimeError):
                pass

    @classmethod
    def from_args(cls, args) -> "ServerApp":
        """Create ServerApp from parsed CLI arguments."""
        engine_type = getattr(args, "engine", "vosk")

        if engine_type == "whisper":
            from .whisper_engine import WhisperEngine

            model_path = getattr(args, "whisper_model", "tiny")
            language = getattr(args, "whisper_language", "fr")
            device = getattr(args, "whisper_device", "auto")
            engine = WhisperEngine(
                model_path=model_path,
                model_size=model_path,
                language=language,
                device=device,
            )
        else:
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

        ssl_context = None
        if getattr(args, "ssl", False):
            ssl_context = _create_ssl_context(args)

        return cls(
            engine=engine,
            llm_processor=llm_processor,
            buffer_config=buffer_config,
            ssl_context=ssl_context,
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
        finally:
            # Force cleanup: close runner's TCP site if still open
            if self._runner:
                try:
                    loop.run_until_complete(self._runner.cleanup())
                except (asyncio.CancelledError, RuntimeError):
                    pass
            # Clear global resources (engine-specific cleanup)
            engine = self._engine
            if hasattr(engine, "_model"):
                engine._model = None
            engine._loaded = False
