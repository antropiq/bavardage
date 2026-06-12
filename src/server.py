"""Real-time French speech transcription server.

Entry point: starts the aiohttp server on port 8765 with WebSocket audio streaming.
Supports multiple transcription engines (Vosk, Whisper) and optional LLM post-processing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from loguru import logger

log = logger

import typer
from typer.main import get_command as typer_get_command
from click.testing import CliRunner

from src.server_app import ServerApp


@dataclass
class ParsedArgs:
    """Namespace-like container for parsed CLI arguments (argparse-compatible)."""
    engine: str
    whisper_model: str
    whisper_language: str
    whisper_device: str
    llm_url: str | None
    llm_key: str | None
    llm_model: str
    llm_timeout: float
    llm_buffer_max: int
    llm_silence_threshold: float
    llm_buffer_min: int
    ssl: bool
    ssl_certfile: str | None
    ssl_keyfile: str | None
    debug: bool
    console: bool


def _build_typer_app():
    """Build and return the Typer CLI app."""
    app = typer.Typer()

    @app.command()
    def _main(
        engine: str = typer.Option("vosk", "--engine", help="Transcription engine (default: vosk)", rich_help_panel="Engine"),
        whisper_model: str = typer.Option("small", "--whisper-model", help="Whisper model size or local path (default: small)", rich_help_panel="Whisper"),
        whisper_language: str = typer.Option("fr", "--whisper-language", help="Language code for Whisper (default: fr)", rich_help_panel="Whisper"),
        whisper_device: str = typer.Option("auto", "--whisper-device", help="Whisper device (default: auto)", rich_help_panel="Whisper"),
        llm_url: str | None = typer.Option(None, "--llm-url", help="LLM API URL (default: disabled)", rich_help_panel="LLM"),
        llm_key: str | None = typer.Option(None, "--llm-key", help="LLM API key (default: none)", rich_help_panel="LLM"),
        llm_model: str = typer.Option("llama3", "--llm-model", help="LLM model name (default: llama3)", rich_help_panel="LLM"),
        llm_timeout: float = typer.Option(15.0, "--llm-timeout", help="LLM API timeout in seconds (default: 15.0)", rich_help_panel="LLM"),
        llm_buffer_max: int = typer.Option(500, "--llm-buffer-max", help="Max buffer size in chars before forced flush (default: 500)", rich_help_panel="LLM"),
        llm_silence_threshold: float = typer.Option(2.0, "--llm-silence-threshold", help="Silence threshold in seconds to trigger flush (default: 2.0)", rich_help_panel="LLM"),
        llm_buffer_min: int = typer.Option(20, "--llm-buffer-min", help="Min buffer size in chars to avoid tiny flushes (default: 20)", rich_help_panel="LLM"),
        ssl: bool = typer.Option(False, "--ssl", help="Enable HTTPS with self-signed certificate", rich_help_panel="SSL"),
        ssl_certfile: str | None = typer.Option(None, "--ssl-certfile", help="Path to SSL certificate file", rich_help_panel="SSL"),
        ssl_keyfile: str | None = typer.Option(None, "--ssl-keyfile", help="Path to SSL private key file", rich_help_panel="SSL"),
        debug: bool = typer.Option(False, "--debug", help="Enable DEBUG-level logging", rich_help_panel="Logging"),
        console: bool = typer.Option(False, "--console", help="Run in console mode (terminal transcription, no server)", rich_help_panel="Console"),
    ):
        if engine not in ("vosk", "whisper"):
            raise typer.BadParameter(f"Invalid engine: {engine}. Must be one of: vosk, whisper")
        return ParsedArgs(
            engine=engine,
            whisper_model=whisper_model,
            whisper_language=whisper_language,
            whisper_device=whisper_device,
            llm_url=llm_url,
            llm_key=llm_key,
            llm_model=llm_model,
            llm_timeout=llm_timeout,
            llm_buffer_max=llm_buffer_max,
            llm_silence_threshold=llm_silence_threshold,
            llm_buffer_min=llm_buffer_min,
            ssl=ssl,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
            debug=debug,
            console=console,
        )

    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments using typer, return argparse.Namespace-compatible object."""
    app = _build_typer_app()
    click_cmd = typer_get_command(app)
    runner = CliRunner()

    target_argv = argv if argv is not None else sys.argv[1:]
    with runner.isolated_filesystem():
        try:
            ctx = click_cmd.make_context("main", target_argv)
            result = ctx.invoke(click_cmd, **ctx.params)
            return result  # type: ignore[return-value]
        except typer.BadParameter as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.exit(2)
        except SystemExit:
            raise


def main() -> None:
    args = parse_args()
    if args.console:
        _run_console_mode(args)
        return
    log_level = "DEBUG" if args.debug else "INFO"
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
    app = ServerApp.from_args(args)
    app.run()


def _run_console_mode(args: ParsedArgs) -> None:
    """Run in console mode using the console module."""
    try:
        from .console import main as console_main
    except ImportError:
        from src.console import main as console_main

    console_argv = ["--engine", args.engine]
    if args.whisper_model:
        console_argv += ["--whisper-model", args.whisper_model]
    if args.whisper_language:
        console_argv += ["--whisper-language", args.whisper_language]
    if args.debug:
        console_argv.append("--debug")
    console_main(console_argv)


def _typer_main() -> None:
    """Typer-compatible entry point that delegates to main()."""
    main()


if __name__ == "__main__":
    _typer_app = _build_typer_app()
    click_cmd = typer.main.get_command(_typer_app)
    try:
        result = click_cmd.main(standalone_mode=False)
    except typer.BadParameter as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(2)
    # --help returns 0 (exit code), not ParsedArgs
    if isinstance(result, int):
        sys.exit(result)
    args = result
    if args.console:
        try:
            from .console import main as console_main
        except ImportError:
            from src.console import main as console_main

        console_argv = ["--engine", args.engine]
        if args.whisper_model:
            console_argv += ["--whisper-model", args.whisper_model]
        if args.whisper_language:
            console_argv += ["--whisper-language", args.whisper_language]
        if args.debug:
            console_argv.append("--debug")
        console_main(console_argv)
    else:
        log_level = "DEBUG" if args.debug else "INFO"
        logger.remove()
        logger.add(sys.stderr, level=log_level, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
        app = ServerApp.from_args(args)
        app.run()
