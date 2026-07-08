"""Unit tests for mars.server.mcp_adapter.MCPAdapter (no subprocess)."""
from __future__ import annotations

import json


from mars.server.services.mcp.adapter import MCPAdapter
from mars.common.constants import TOOL_KEY, TOOL_ARGS_KEY


class TestMCPAdapterInit:
    def test_instantiation_with_command(self):
        adapter = MCPAdapter(agent_id="svc.test@1", command=["echo", "hello"])
        assert adapter.agent_id == "svc.test@1"
        assert adapter._command == ["echo", "hello"]
        assert adapter._proc is None


class TestEnvelopeDetection:
    """The server routes tool envelopes — verify the key format is consistent."""

    def test_tool_key_and_args_key_constants(self):
        envelope = {TOOL_KEY: "my_tool", TOOL_ARGS_KEY: {"q": "test"}}
        assert envelope[TOOL_KEY] == "my_tool"
        assert envelope[TOOL_ARGS_KEY]["q"] == "test"

    def test_envelope_serialises_to_json(self):
        envelope = json.dumps({TOOL_KEY: "search", TOOL_ARGS_KEY: {"query": "mars"}})
        decoded = json.loads(envelope)
        assert decoded[TOOL_KEY] == "search"
