"""LLMPostProcessor: post-processes transcribed text via an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
from loguru import logger

from openai import AsyncOpenAI, APIError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import LLMConfig

log = logger


class LLMPostProcessor:
    """Post-processes transcribed text via an OpenAI-compatible LLM API.

    If the LLM is unavailable or fails, the original raw text is returned
    as a fallback — transcription never blocks or crashes.
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str = "llama3",
        system_prompt: str | None = None,
        timeout: float = 5.0,
        max_retries: int = 1,
        config: LLMConfig | None = None,
    ) -> None:
        if config is not None:
            self._config = config
            base_url = config.base_url
            self._api_key = config.api_key
            self._model = config.model
            self._system_prompt = system_prompt or config.system_prompt or self._default_system_prompt()
            self._timeout = config.timeout
            self._max_retries = config.max_retries
        else:
            self._config = None
            base_url = (api_url or "").rstrip("/")
            self._api_key = api_key
            self._model = model
            self._system_prompt = system_prompt or self._default_system_prompt()
            self._timeout = timeout
            self._max_retries = max_retries

        self._api_url = base_url
        self._enabled = bool(base_url)
        if self._enabled:
            client_key = self._api_key or "sk-dummy-key-for-testing"
            self._client = AsyncOpenAI(base_url=f"{base_url}/v1", api_key=client_key)
        else:
            self._client = None  # type: ignore[assignment]
        log.debug(
            "LLMPostProcessor initialized: url=%s model=%s enabled=%s",
            self._api_url,
            self._model,
            self._enabled,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are a French text post-processor for speech recognition output. "
            "You receive two parts:\n"
            "1. CONTEXT: previously transcribed and corrected text (DO NOT MODIFY)\n"
            "2. FRAGMENT: a new piece of raw ASR output that needs correction\n\n"
            "Your ONLY task is to correct the FRAGMENT: add proper punctuation, fix "
            "capitalization, and repair minor ASR errors. Use the CONTEXT to understand "
            "pronouns, references, and resolve ambiguities (ses/ces, ou/où, et/est, etc.).\n\n"
            "CRITICAL: Output ONLY the corrected fragment. NEVER repeat the context. "
            "NEVER answer questions, add commentary, or change the original meaning. "
            "Output ONLY the corrected French text — no greetings, no explanations, no extra text."
        )

    async def process(self, raw_text: str, context: str = "") -> str:
        """Send raw text to LLM and return polished text.

        On failure, returns the original ``raw_text`` (fallback).

        Args:
            raw_text: The ASR fragment to correct.
            context: Previously corrected text for disambiguation.
        """
        if not self._enabled or not raw_text.strip():
            return raw_text

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._call_llm(raw_text, context=context)
                polished = self._extract_text(response)
                if polished:
                    return polished
                log.warning("LLM returned empty response for attempt {}", attempt + 1)
                if attempt == self._max_retries:
                    return raw_text
                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as e:
                log.warning("LLM call failed (attempt {}/{}): {}", attempt + 1, self._max_retries + 1, e)
                return raw_text

        return raw_text

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5.0),
        retry=retry_if_exception_type((APIError, APITimeoutError)),
        reraise=True,
    )
    async def _call_llm(
        self,
        raw_text: str,
        context: str = "",
        system_prompt: str | None = None,
    ) -> object:
        """Call the OpenAI-compatible API with automatic retry on failure."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt or self._system_prompt},
        ]
        if context.strip():
            messages.append({"role": "user", "content": f"Contexte: {context}\n\nFragment: {raw_text}"})
        else:
            messages.append({"role": "user", "content": raw_text})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=1024,
            temperature=0.0,
            timeout=self._timeout,
        )
        return response

    @staticmethod
    def _extract_text(response: object) -> str:
        """Extract text from LLM API response."""
        try:
            choice = response.choices[0]
            content = choice.message.content
            return content.strip() if content else ""
        except (AttributeError, IndexError):
            return ""
