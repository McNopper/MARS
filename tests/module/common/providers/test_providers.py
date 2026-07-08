"""Tests for MARS provider adapters."""

from __future__ import annotations

import pytest

from mars.server.services.llm.base import LLMMessage, LLMResponse, ModelInfo, ToolSpec
from mars.server.services.llm.mock import MockService
from mars.server.services.registry import get_service, list_services


class TestMockService:
    def test_default_response(self):
        p = MockService(response="hello")
        assert p._fixed == "hello"

    @pytest.mark.asyncio
    async def test_complete_returns_fixed_response(self):
        p = MockService(response="test reply", delay=0.0)
        msgs = [LLMMessage(role="user", content="hi")]
        result = await p.complete(msgs)
        assert result.content == "test reply"
        assert result.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_complete_rotates_when_no_fixed_response(self):
        p = MockService(delay=0.0)
        msgs = [LLMMessage(role="user", content="hello")]
        responses = {(await p.complete(msgs)).content for _ in range(20)}
        assert len(responses) > 1

    @pytest.mark.asyncio
    async def test_complete_ignores_tools(self):
        class FakeTool:
            name = "noop"
            description = "does nothing"
            parameters: dict = {}

        p = MockService(response="ok", delay=0.0)
        msgs = [LLMMessage(role="user", content="hi")]
        result = await p.complete(msgs, tools=[FakeTool()])  # type: ignore[list-item]
        assert result.content == "ok"

    def test_model_property(self):
        assert MockService().model == "mock-1.0"

    def test_provider_name(self):
        assert MockService().provider_name == "mock"

    @pytest.mark.asyncio
    async def test_list_models(self):
        models = await MockService().list_models()
        assert len(models) >= 1
        assert all(isinstance(m, ModelInfo) for m in models)


class TestLLMMessage:
    def test_defaults(self):
        msg = LLMMessage(role="user")
        assert msg.content is None
        assert msg.tool_calls == []
        assert msg.tool_call_id is None
        assert msg.name is None

    def test_tool_role(self):
        msg = LLMMessage(role="tool", content="result", tool_call_id="call-1", name="my_tool")
        assert msg.role == "tool"
        assert msg.tool_call_id == "call-1"


class TestLLMResponse:
    def test_defaults(self):
        r = LLMResponse(content="hello")
        assert r.finish_reason == "stop"
        assert r.tool_calls == []
        assert r.raw is None

    def test_none_content(self):
        r = LLMResponse(content=None, tool_calls=[{"id": "x"}])
        assert r.content is None
        assert len(r.tool_calls) == 1


class TestModelInfo:
    def test_name_defaults_to_id(self):
        assert ModelInfo(id="gpt-4o-mini").name == "gpt-4o-mini"

    def test_explicit_name(self):
        assert ModelInfo(id="gpt-4o-mini", name="GPT-4o mini").name == "GPT-4o mini"

    def test_is_free_default_false(self):
        assert ModelInfo(id="gpt-4o").is_free is False


class TestToolSpec:
    def test_structural_subtyping(self):
        class MyTool:
            name = "say_hello"
            description = "Greets the world"
            parameters: dict = {"type": "object", "properties": {}}

        assert isinstance(MyTool(), ToolSpec)

    def test_missing_field_not_subtype(self):
        class BadTool:
            name = "broken"

        assert not isinstance(BadTool(), ToolSpec)


class TestProviderRegistry:
    def test_list_services_includes_mock(self):
        assert "mock" in list_services(include_test=True)

    def test_get_mock_provider(self):
        assert isinstance(get_service("mock"), MockService)

    def test_unknown_provider_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_service("does-not-exist-xyz")
