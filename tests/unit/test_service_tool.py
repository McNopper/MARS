"""Unit tests for _ServiceTool and the launcher agent parser."""
from __future__ import annotations

import pytest

from mars.services.launcher_agent import _parse_spawn_request
from mars.services.llm_wire_agent import _ServiceTool


class TestServiceToolName:
    def test_uses_first_skill_as_name(self):
        t = _ServiceTool(agent_id="svc.clock@1", skills=["get_time", "time", "clock"])
        assert t.name == "get_time"

    def test_math_agent_name(self):
        t = _ServiceTool(agent_id="svc.math@1", skills=["solve_math", "math", "sympy"])
        assert t.name == "solve_math"

    def test_fallback_to_agent_id_when_no_skills(self):
        t = _ServiceTool(agent_id="svc.clock@1", skills=[])
        assert t.name == "svc_clock_1"

    def test_sanitises_special_chars(self):
        t = _ServiceTool(agent_id="svc.foo@1", skills=["my-skill.v2"])
        # hyphens and dots → underscores
        assert t.name == "my_skill_v2"

    def test_name_is_valid_identifier(self):
        for skills in [["get_time"], ["solve_math"], ["list_ollama_models"]]:
            t = _ServiceTool(agent_id="svc.x@1", skills=skills)
            assert t.name.isidentifier(), f"{t.name!r} is not a valid identifier"


class TestServiceToolDescription:
    def test_includes_primary_skill(self):
        t = _ServiceTool(agent_id="svc.clock@1", skills=["get_time", "time", "clock"])
        assert "get_time" in t.description

    def test_lists_aliases(self):
        t = _ServiceTool(agent_id="svc.clock@1", skills=["get_time", "time", "clock", "location"])
        assert "time" in t.description
        assert "clock" in t.description

    def test_no_crash_single_skill(self):
        t = _ServiceTool(agent_id="svc.x@1", skills=["only_skill"])
        desc = t.description
        assert "only_skill" in desc


class TestServiceToolParameters:
    def test_has_request_property(self):
        t = _ServiceTool(agent_id="svc.clock@1", skills=["get_time"])
        params = t.parameters
        assert "request" in params["properties"]
        assert "request" in params.get("required", [])


class TestLauncherParseRequest:
    def test_plain_provider_only(self):
        provider, model = _parse_spawn_request("anthropic")
        assert provider == "anthropic"
        assert model == ""

    def test_plain_provider_and_model(self):
        provider, model = _parse_spawn_request("ollama llama3.2")
        assert provider == "ollama"
        assert model == "llama3.2"

    def test_json_provider_only(self):
        provider, model = _parse_spawn_request('{"provider": "copilot"}')
        assert provider == "copilot"
        assert model == ""

    def test_json_provider_and_model(self):
        provider, model = _parse_spawn_request(
            '{"provider": "anthropic", "model": "claude-opus-4-7"}'
        )
        assert provider == "anthropic"
        assert model == "claude-opus-4-7"

    def test_empty_text_returns_empty(self):
        provider, model = _parse_spawn_request("")
        assert provider == ""
        assert model == ""

    def test_provider_normalised_to_lowercase(self):
        provider, _ = _parse_spawn_request("Anthropic")
        assert provider == "anthropic"

    def test_model_with_spaces_preserved(self):
        provider, model = _parse_spawn_request("ollama some-model extra")
        assert provider == "ollama"
        assert model == "some-model extra"
