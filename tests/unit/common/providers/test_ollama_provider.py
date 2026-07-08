"""Unit tests for mars.common.providers.ollama.

Covers:
- _supports_tools: model name matching
- OllamaService.__init__: base_url construction, default model
- OllamaService.list_models: graceful fallback when Ollama not running
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from mars.server.services.llm.ollama import OllamaService, _supports_tools


# ---------------------------------------------------------------------------
# _supports_tools
# ---------------------------------------------------------------------------

class TestSupportsTools:
    def test_llama3_2_supported(self) -> None:
        assert _supports_tools("llama3.2") is True

    def test_llama3_2_tagged(self) -> None:
        assert _supports_tools("llama3.2:latest") is True

    def test_llama3_3_supported(self) -> None:
        assert _supports_tools("llama3.3") is True

    def test_qwen_supported(self) -> None:
        assert _supports_tools("qwen2.5:7b") is True

    def test_mistral_supported(self) -> None:
        assert _supports_tools("mistral") is True

    def test_phi4_not_supported(self) -> None:
        assert _supports_tools("phi4") is False

    def test_gemma_not_supported(self) -> None:
        assert _supports_tools("gemma3:4b") is False

    def test_unknown_model_not_supported(self) -> None:
        assert _supports_tools("some-unknown-model") is False


# ---------------------------------------------------------------------------
# OllamaService construction
# ---------------------------------------------------------------------------

class TestOllamaServiceInit:
    def _make_provider(self, model: str = "llama3.2", host: str = "http://localhost:11434"):
        with mock.patch("openai.AsyncOpenAI"):
            return OllamaService(model=model, host=host)

    def test_default_model(self) -> None:
        p = self._make_provider()
        assert p._model == "llama3.2"

    def test_custom_model(self) -> None:
        p = self._make_provider(model="mistral")
        assert p._model == "mistral"

    def test_base_url_uses_v1_suffix(self) -> None:
        p = self._make_provider(host="http://localhost:11434")
        assert p._host == "http://localhost:11434"

    def test_trailing_slash_stripped(self) -> None:
        p = self._make_provider(host="http://localhost:11434/")
        assert p._host == "http://localhost:11434"

    def test_custom_host(self) -> None:
        p = self._make_provider(host="http://my-server:11434")
        assert p._host == "http://my-server:11434"


# ---------------------------------------------------------------------------
# list_models graceful fallback
# ---------------------------------------------------------------------------

class TestListModelsFallback:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_ollama_unreachable(self) -> None:
        with mock.patch("openai.AsyncOpenAI"):
            p = OllamaService(model="llama3.2")

        import httpx
        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=False)
            mock_client.get.side_effect = httpx.ConnectError("connection refused")
            mock_client_cls.return_value = mock_client
            result = await p.list_models()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_model_list_on_success(self) -> None:
        with mock.patch("openai.AsyncOpenAI"):
            p = OllamaService(model="llama3.2")

        mock_resp = mock.MagicMock()
        mock_resp.raise_for_status = mock.MagicMock()
        mock_resp.json.return_value = {
            "models": [
                {"name": "llama3.2:latest", "size": 2_000_000_000,
                 "details": {"context_length": 8192}},
                {"name": "mistral:latest", "size": 4_000_000_000,
                 "details": {}},
            ]
        }

        with mock.patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = mock.AsyncMock()
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            result = await p.list_models()

        assert len(result) == 2
        assert result[0].id == "llama3.2:latest"
        assert result[0].context_window == 8192
        assert result[1].id == "mistral:latest"
