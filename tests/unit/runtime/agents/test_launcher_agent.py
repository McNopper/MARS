"""Unit tests for mars.runtime.agents.launcher_agent.

Covers:
- _parse_spawn_request: positional and JSON formats
"""
from __future__ import annotations

import json

import pytest

from mars.runtime.agents.launcher_agent import _parse_spawn_request


class TestParseSpawnRequest:
    def test_provider_only(self) -> None:
        provider, model = _parse_spawn_request("anthropic")
        assert provider == "anthropic"
        assert model == ""

    def test_provider_and_model_positional(self) -> None:
        provider, model = _parse_spawn_request("ollama llama3.2")
        assert provider == "ollama"
        assert model == "llama3.2"

    def test_json_object(self) -> None:
        provider, model = _parse_spawn_request(
            json.dumps({"provider": "anthropic", "model": "claude-opus-4-7"})
        )
        assert provider == "anthropic"
        assert model == "claude-opus-4-7"

    def test_json_provider_only(self) -> None:
        provider, model = _parse_spawn_request(json.dumps({"provider": "copilot"}))
        assert provider == "copilot"
        assert model == ""

    def test_empty_string(self) -> None:
        provider, model = _parse_spawn_request("")
        assert provider == ""
        assert model == ""

    def test_provider_lowercased(self) -> None:
        provider, _ = _parse_spawn_request("OLLAMA")
        assert provider == "ollama"

    def test_model_with_tag(self) -> None:
        provider, model = _parse_spawn_request("ollama qwen2.5:7b")
        assert provider == "ollama"
        assert model == "qwen2.5:7b"

    def test_json_missing_provider(self) -> None:
        provider, model = _parse_spawn_request(json.dumps({"model": "llama3.2"}))
        assert provider == ""
        assert model == "llama3.2"
