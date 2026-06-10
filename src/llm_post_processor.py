"""LLMPostProcessor: post-processes transcribed text via an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
import logging

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
        log.info(
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
            "Your task is to: "
            "1. Add proper punctuation (commas, periods, question marks, exclamation marks) "
            "2. Capitalize correctly "
            "3. Fix minor ASR errors (wrong words, missing spaces) "
            "4. Preserve the original meaning and tone "
            "5. Output ONLY the corrected French text, nothing else "
            "Do not add greetings, explanations, or any text beyond the corrected transcription."
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

    async def _call_llm(self, raw_text: str) -> dict:
        """Call the OpenAI-compatible API."""
        import aiohttp

        url = f"{self._api_url}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": raw_text},
            ],
            "max_tokens": 1024,
            "temperature": 0.0,
        }

        async with aiohttp.ClientSession() as session:
            timeout_obj = aiohttp.ClientTimeout(total=self._timeout)
            async with session.post(url, json=payload, headers=headers, timeout=timeout_obj) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    def _extract_text(response: dict) -> str:
        """Extract text from LLM API response."""
        try:
            return response["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError):
            return ""
