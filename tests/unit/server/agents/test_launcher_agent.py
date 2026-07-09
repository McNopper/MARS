"""Unit tests for _parse_spawn_request in mars.server.services.builtin.launcher_service."""
from __future__ import annotations

import json


from mars.server.services.builtin.launcher_service import _parse_spawn_request


class TestParseSpawnRequest:
    def test_provider_only(self) -> None:
        args = _parse_spawn_request("anthropic")
        assert args == {"provider": "anthropic"}

    def test_provider_and_model_positional(self) -> None:
        args = _parse_spawn_request("ollama llama3.2")
        assert args["provider"] == "ollama"
        assert args["model"] == "llama3.2"

    def test_json_object(self) -> None:
        args = _parse_spawn_request(
            json.dumps({"provider": "anthropic", "model": "claude-opus-4-8"})
        )
        assert args["provider"] == "anthropic"
        assert args["model"] == "claude-opus-4-8"

    def test_json_provider_only(self) -> None:
        args = _parse_spawn_request(json.dumps({"provider": "copilot"}))
        assert args == {"provider": "copilot"}

    def test_empty_string(self) -> None:
        assert _parse_spawn_request("") == {}

    def test_provider_lowercased(self) -> None:
        assert _parse_spawn_request("OLLAMA")["provider"] == "ollama"

    def test_json_provider_lowercased(self) -> None:
        assert _parse_spawn_request(json.dumps({"provider": "Anthropic"}))["provider"] == "anthropic"

    def test_model_with_tag(self) -> None:
        args = _parse_spawn_request("ollama qwen2.5:7b")
        assert args["provider"] == "ollama"
        assert args["model"] == "qwen2.5:7b"

    def test_json_missing_provider(self) -> None:
        args = _parse_spawn_request(json.dumps({"model": "llama3.2"}))
        assert "provider" not in args
        assert args["model"] == "llama3.2"

    def test_json_full_phase_spawn(self) -> None:
        data = {
            "provider": "copilot",
            "model": "gpt-4o",
            "name": "phase.swe2_architecture",
            "system_prompt": "You are a phase coordinator.",
            "kickoff": "Start now.",
        }
        args = _parse_spawn_request(json.dumps(data))
        assert args["provider"] == "copilot"
        assert args["model"] == "gpt-4o"
        assert args["name"] == "phase.swe2_architecture"
        assert args["system_prompt"] == "You are a phase coordinator."
        assert args["kickoff"] == "Start now."

    def test_json_claude_knobs(self) -> None:
        data = {
            "provider": "anthropic",
            "model": "claude-opus-4-8",
            "thinking": True,
            "cache_prompts": False,
            "max_tokens": 16000,
        }
        args = _parse_spawn_request(json.dumps(data))
        assert "effort" not in args
        assert args["thinking"] is True
        assert args["cache_prompts"] is False
        assert args["max_tokens"] == 16000

    def test_json_allowed_skills_from_either_key(self) -> None:
        a = _parse_spawn_request(json.dumps({"provider": "anthropic", "allowed_skills": ["a", "b"]}))
        b = _parse_spawn_request(json.dumps({"provider": "anthropic", "skills": ["c"]}))
        assert a["allowed_skills"] == ["a", "b"]
        assert b["allowed_skills"] == ["c"]
