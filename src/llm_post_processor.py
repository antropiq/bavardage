"""LLMPostProcessor: post-processes transcribed text via an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)


class LLMPostProcessor:
    """Post-processes transcribed text via an OpenAI-compatible LLM API.

    If the LLM is unavailable or fails, the original raw text is returned
    as a fallback — transcription never blocks or crashes.
    """

    def __init__(
        self,
        api_url: str,
        api_key: str | None = None,
        model: str = "llama3",
        system_prompt: str | None = None,
        timeout: float = 5.0,
        max_retries: int = 1,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt or self._default_system_prompt()
        self._timeout = timeout
        self._max_retries = max_retries
        self._enabled = bool(api_url)
        self._session: aiohttp.ClientSession | None = None
        log.debug(
            "LLMPostProcessor initialized: url=%s model=%s enabled=%s",
            self._api_url,
            self._model,
            self._enabled,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure we have a valid aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @staticmethod
    def _default_system_prompt() -> str:
        return (
            "You are a French text post-processor for speech recognition output. "
            "Your ONLY task is to correct the text: add proper punctuation, fix capitalization, "
            "and repair minor ASR errors. NEVER answer questions, add commentary, or change "
            "the original meaning. Output ONLY the corrected French text — no greetings, "
            "no explanations, no extra text."
        )

    async def process(self, raw_text: str) -> str:
        """Send raw text to LLM and return polished text.

        On failure, returns the original ``raw_text`` (fallback).
        """
        if not self._enabled or not raw_text.strip():
            return raw_text

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._call_llm(raw_text)
                polished = self._extract_text(response)
                if polished:
                    return polished
                log.warning("LLM returned empty response for attempt %d", attempt + 1)
                if attempt == self._max_retries:
                    return raw_text
                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as e:
                log.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, self._max_retries + 1, e)
                if attempt == self._max_retries:
                    return raw_text
                await asyncio.sleep(0.5 * (attempt + 1))

        return raw_text

    async def _call_llm(self, raw_text: str, system_prompt: str | None = None) -> dict:
        """Call the OpenAI-compatible API."""
        url = f"{self._api_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        messages = [
            {"role": "system", "content": system_prompt or self._system_prompt},
            {"role": "user", "content": raw_text},
        ]

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.0,
        }

        session = await self._ensure_session()
        timeout_obj = aiohttp.ClientTimeout(total=self._timeout)
        async with session.post(url, json=payload, headers=headers, timeout=timeout_obj) as resp:
            if resp.status >= 400:
                error_body = await resp.text()
                raise Exception(f"LLM API error {resp.status}: {error_body[:500]}")
            return await resp.json()

    @staticmethod
    def _extract_text(response: dict) -> str:
        """Extract text from LLM API response."""
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            return ""
