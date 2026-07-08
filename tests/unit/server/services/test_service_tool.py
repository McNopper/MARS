"""Unit tests for _ServiceTool and the launcher agent parser."""
from __future__ import annotations


from mars.server.services.llm_wire_agent import _ServiceTool


def _make(agent_id: str, skills: list[str]) -> _ServiceTool:
    """Build a generic-schema _ServiceTool the same way the wire agent does on spawn."""
    tools = _ServiceTool.from_spawn(agent_id, skills, tool_schemas=[])
    return tools[0]


class TestServiceToolName:
    def test_uses_first_skill_as_name(self):
        t = _make("svc.clock@1", ["get_time", "time", "clock"])
        assert t.name == "get_time"

    def test_sympy_agent_name(self):
        t = _make("svc.sympy@1", ["solve_math", "math", "sympy"])
        assert t.name == "solve_math"

    def test_fallback_to_agent_id_when_no_skills(self):
        t = _make("svc.clock@1", [])
        assert t.name == "svc_clock_1"

    def test_sanitises_special_chars(self):
        t = _make("svc.foo@1", ["my-skill.v2"])
        # hyphens and dots → underscores
        assert t.name == "my_skill_v2"

    def test_name_is_valid_identifier(self):
        for skills in [["get_time"], ["solve_math"], ["list_ollama_models"]]:
            t = _make("svc.x@1", skills)
            assert t.name.isidentifier(), f"{t.name!r} is not a valid identifier"


class TestServiceToolDescription:
    def test_includes_primary_skill(self):
        t = _make("svc.clock@1", ["get_time", "time", "clock"])
        assert "get_time" in t.description

    def test_lists_aliases(self):
        t = _make("svc.clock@1", ["get_time", "time", "clock", "location"])
        assert "time" in t.description
        assert "clock" in t.description

    def test_no_crash_single_skill(self):
        t = _make("svc.x@1", ["only_skill"])
        assert "only_skill" in t.description


class TestServiceToolParameters:
    def test_generic_fallback_has_request_property(self):
        t = _make("svc.clock@1", ["get_time"])
        params = t.parameters
        assert "request" in params["properties"]
        assert "request" in params.get("required", [])

    def test_real_schema_passed_through(self):
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "page": {"type": "integer"},
            },
            "required": ["query"],
        }
        tools = _ServiceTool.from_spawn(
            "svc.github@1",
            ["search_repositories"],
            tool_schemas=[{"name": "search_repositories", "description": "Search repos", "input_schema": schema}],
        )
        assert len(tools) == 1
        assert tools[0].name == "search_repositories"
        assert tools[0].parameters == schema

    def test_one_tool_per_schema(self):
        schemas = [
            {"name": "tool_a", "description": "A", "input_schema": {}},
            {"name": "tool_b", "description": "B", "input_schema": {}},
        ]
        tools = _ServiceTool.from_spawn("svc.ext@1", ["tool_a", "tool_b"], tool_schemas=schemas)
        assert [t.name for t in tools] == ["tool_a", "tool_b"]
        # NOTE: launcher _parse_spawn_request coverage lives in
        # tests/unit/runtime/agents/test_launcher_agent.py (the canonical home).
