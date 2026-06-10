"""Unit tests for LLMPostProcessor."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
    mock_response = {
        "choices": [{"message": {"content": "Bonjour, comment allez-vous ?"}}]
    }
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
    mock_response = {"choices": [{"message": {"content": "   "}}]}
    with patch.object(proc, "_call_llm", new_callable=AsyncMock, return_value=mock_response):
        result = asyncio.run(proc.process("test text"))
    assert result == "test text"


def test_process_bad_response_format_returns_raw():
    proc = LLMPostProcessor(api_url="http://test:8080")
    mock_response = {"data": "no choices here"}
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


if __name__ == "__main__":
    test_disabled_returns_raw()
    test_empty_string_returns_raw()
    test_process_success()
    test_process_api_failure_returns_raw()
    test_process_empty_response_returns_raw()
    test_process_bad_response_format_returns_raw()
    test_system_prompt_default()
    test_system_prompt_custom()
    print("All LLMPostProcessor tests passed!")
