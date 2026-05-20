"""Unit tests for the structured tool-call envelope and _ServiceTool.from_spawn.

These tests cover the new behaviour introduced to support external MCP servers
with multi-parameter tools (e.g. the GitHub MCP server).  No I/O or subprocesses.
"""
from __future__ import annotations

import json

import pytest

from mars.runtime.services.llm_wire_agent import _ServiceTool


# ---------------------------------------------------------------------------
# _ServiceTool.from_spawn — schema passthrough
# ---------------------------------------------------------------------------

class TestFromSpawnWithSchemas:
    def test_one_tool_per_schema_entry(self):
        schemas = [
            {"name": "search_repositories", "description": "Search repos", "input_schema": {}},
            {"name": "get_file_contents",   "description": "Read a file",  "input_schema": {}},
        ]
        tools = _ServiceTool.from_spawn("svc.github@1", [], tool_schemas=schemas)
        assert len(tools) == 2
        assert [t.name for t in tools] == ["search_repositories", "get_file_contents"]

    def test_real_schema_stored_verbatim(self):
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "page":  {"type": "integer", "default": 1},
            },
            "required": ["query"],
        }
        tools = _ServiceTool.from_spawn(
            "svc.github@1",
            ["search_repositories"],
            tool_schemas=[{"name": "search_repositories", "description": "d", "input_schema": schema}],
        )
        assert tools[0].parameters == schema

    def test_description_from_schema(self):
        tools = _ServiceTool.from_spawn(
            "svc.github@1",
            [],
            tool_schemas=[{"name": "create_issue", "description": "Create a GitHub issue", "input_schema": {}}],
        )
        assert tools[0].description == "Create a GitHub issue"

    def test_agent_id_stored_on_all_tools(self):
        schemas = [
            {"name": "tool_a", "description": "", "input_schema": {}},
            {"name": "tool_b", "description": "", "input_schema": {}},
        ]
        tools = _ServiceTool.from_spawn("svc.ext@1", [], tool_schemas=schemas)
        assert all(t.agent_id == "svc.ext@1" for t in tools)

    def test_missing_input_schema_falls_back_to_generic(self):
        tools = _ServiceTool.from_spawn(
            "svc.ext@1",
            [],
            tool_schemas=[{"name": "my_tool", "description": "desc"}],  # no input_schema key
        )
        params = tools[0].parameters
        assert "request" in params["properties"]

    def test_none_input_schema_falls_back_to_generic(self):
        tools = _ServiceTool.from_spawn(
            "svc.ext@1",
            [],
            tool_schemas=[{"name": "my_tool", "description": "desc", "input_schema": None}],
        )
        assert "request" in tools[0].parameters["properties"]


class TestFromSpawnWithoutSchemas:
    def test_single_generic_tool_created(self):
        tools = _ServiceTool.from_spawn("svc.clock@1", ["get_time", "time", "clock"], tool_schemas=[])
        assert len(tools) == 1

    def test_tool_name_is_primary_skill(self):
        tools = _ServiceTool.from_spawn("svc.clock@1", ["get_time", "time"], tool_schemas=[])
        assert tools[0].name == "get_time"

    def test_fallback_uses_agent_id_when_no_skills(self):
        tools = _ServiceTool.from_spawn("svc.clock@1", [], tool_schemas=[])
        assert tools[0].name == "svc_clock_1"

    def test_generic_schema_has_request_param(self):
        tools = _ServiceTool.from_spawn("svc.clock@1", ["get_time"], tool_schemas=[])
        params = tools[0].parameters
        assert "request" in params["properties"]
        assert "request" in params["required"]


# ---------------------------------------------------------------------------
# _ServiceTool name sanitisation
# ---------------------------------------------------------------------------

class TestToolNameSanitisation:
    @pytest.mark.parametrize("raw,expected", [
        ("search_repositories", "search_repositories"),
        ("get-file-contents",   "get_file_contents"),
        ("my.tool.v2",          "my_tool_v2"),
        ("tool name",           "tool_name"),
    ])
    def test_sanitised_name(self, raw, expected):
        tools = _ServiceTool.from_spawn(
            "svc.x@1", [],
            tool_schemas=[{"name": raw, "description": "", "input_schema": {}}],
        )
        assert tools[0].name == expected

    def test_name_is_valid_python_identifier(self):
        for raw in ["search_repositories", "get_file_contents", "create_issue"]:
            tools = _ServiceTool.from_spawn(
                "svc.x@1", [],
                tool_schemas=[{"name": raw, "description": "", "input_schema": {}}],
            )
            assert tools[0].name.isidentifier()


# ---------------------------------------------------------------------------
# Structured envelope format
# ---------------------------------------------------------------------------

class TestStructuredEnvelope:
    """Verify the envelope the wire agent sends is parseable by the server."""

    def test_envelope_round_trips_as_json(self):
        tool_name = "search_repositories"
        args = {"query": "mars multi-agent", "page": 1}
        envelope = json.dumps({"__tool__": tool_name, "__args__": args})

        parsed = json.loads(envelope)
        assert parsed["__tool__"] == tool_name
        assert parsed["__args__"] == args

    def test_server_detects_envelope(self):
        """Simulate the server-side envelope detection logic."""
        text = json.dumps({"__tool__": "get_time", "__args__": {}})
        try:
            envelope = json.loads(text)
            has_tool = isinstance(envelope, dict) and "__tool__" in envelope
        except (json.JSONDecodeError, TypeError):
            has_tool = False
        assert has_tool

    def test_plain_text_not_detected_as_envelope(self):
        for text in ["what is the time?", '{"request": "solve x^2"}', ""]:
            try:
                envelope = json.loads(text)
                has_tool = isinstance(envelope, dict) and "__tool__" in envelope
            except (json.JSONDecodeError, TypeError):
                has_tool = False
            assert not has_tool, f"Plain text {text!r} incorrectly detected as envelope"
