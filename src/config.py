"""Configuration models for the realtime-speech server.

Uses Pydantic for validated, self-documenting configuration with IDE autocomplete.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class LLMConfig(BaseModel):
    """Configuration for the LLM post-processing API."""

    api_url: HttpUrl
    api_key: str | None = None
    model: str = "llama3"
    timeout: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=1, ge=0)
    system_prompt: str | None = None

    @property
    def base_url(self) -> str:
        """Return the API base URL without trailing slash."""
        return str(self.api_url).rstrip("/")


class ServerConfig(BaseModel):
    """Top-level server configuration."""

    engine: str = Field(default="vosk", pattern="^(vosk|whisper)$")
    whisper_model: str = "small"
    whisper_language: str = "fr"
    whisper_device: str = "auto"
    llm: LLMConfig | None = None
    ssl: bool = False
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None
    debug: bool = False
    llm_buffer_max: int = 500
    llm_silence_threshold: float = 2.0
    llm_buffer_min: int = 20

    @property
    def buffer_config(self) -> dict:
        """Return buffer configuration dict for TranscriptionBuffer."""
        return {
            "max_buffer_size": self.llm_buffer_max,
            "silence_threshold": self.llm_silence_threshold,
            "min_buffer_size": self.llm_buffer_min,
        }
