"""Unit tests for LLMPostProcessor."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm_post_processor import LLMPostProcessor


def test_disabled_returns_raw():
    proc = LLMPostProcessor(api_url="")
    assert proc.enabled is False
    result = asyncio.run(proc.process("test"))
    assert result == "test"


def test_empty_string_returns_raw():
    proc = LLMPostProcessor(api_url="http://test:8080")
    assert proc.enabled is True
    result = asyncio.run(proc.process(""))
    assert result == ""


def test_process_success():
    proc = LLMPostProcessor(api_url="http://test:8080", model="llama3")
    mock_choice = MagicMock()
    mock_choice.message.content = "Bonjour, comment allez-vous ?"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    with patch.object(proc, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = asyncio.run(proc.process("bonjour comment allez vous"))
    assert result == "Bonjour, comment allez-vous ?"


def test_process_api_failure_returns_raw():
    proc = LLMPostProcessor(api_url="http://test:8080")
    with patch.object(proc, "_call_llm", new_callable=AsyncMock, side_effect=Exception("network error")):
        result = asyncio.run(proc.process("test text"))
    assert result == "test text"


def test_process_empty_response_returns_raw():
    proc = LLMPostProcessor(api_url="http://test:8080")
    mock_choice = MagicMock()
    mock_choice.message.content = "   "
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    with patch.object(proc, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = asyncio.run(proc.process("test text"))
    assert result == "test text"


def test_process_bad_response_format_returns_raw():
    proc = LLMPostProcessor(api_url="http://test:8080")
    mock_response = MagicMock()
    mock_response.choices = []
    with patch.object(proc, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = asyncio.run(proc.process("test text"))
    assert result == "test text"


def test_system_prompt_default():
    proc = LLMPostProcessor(api_url="http://test:8080")
    assert "French text post-processor" in proc._system_prompt
    assert "Output ONLY the corrected French text" in proc._system_prompt


def test_system_prompt_custom():
    custom = "Be funny"
    proc = LLMPostProcessor(api_url="http://test:8080", system_prompt=custom)
    assert proc._system_prompt == custom


def test_base_url_trailing_slash_stripped():
    proc = LLMPostProcessor(api_url="http://test:8080/")
    assert str(proc._client.base_url) == "http://test:8080/v1/"


def test_client_is_none_when_disabled():
    proc = LLMPostProcessor(api_url="")
    assert proc._client is None


def test_api_key_passed_to_client():
    proc = LLMPostProcessor(api_url="http://test:8080", api_key="my-secret-key")
    assert proc._client.api_key == "my-secret-key"


if __name__ == "__main__":
    test_disabled_returns_raw()
    test_empty_string_returns_raw()
    test_process_success()
    test_process_api_failure_returns_raw()
    test_process_empty_response_returns_raw()
    test_process_bad_response_format_returns_raw()
    test_system_prompt_default()
    test_system_prompt_custom()
    test_base_url_trailing_slash_stripped()
    test_api_key_passed_to_client()
    print("All LLMPostProcessor tests passed!")
