"""Unit tests for A2AAdapter and build_mars_agent_card."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mars.server.services.a2a.adapter import (
    A2AAdapter,
    AgentCard,
    _extract_text,
    _parts_to_texts,
    build_mars_agent_card,
)


# ── build_mars_agent_card ─────────────────────────────────────────────────────

class TestBuildMarsAgentCard:
    def test_returns_dict_with_required_fields(self):
        card = build_mars_agent_card("MyNode", "http://localhost:7433/a2a")
        assert card["name"] == "MyNode"
        assert card["url"] == "http://localhost:7433/a2a/"
        assert "skills" in card
        assert "capabilities" in card
        assert "defaultInputModes" in card
        assert "defaultOutputModes" in card

    def test_default_skills_present(self):
        card = build_mars_agent_card("MARS", "http://localhost:7433/a2a")
        skill_ids = [s["id"] for s in card["skills"]]
        assert "chat" in skill_ids
        assert "reasoning" in skill_ids

    def test_custom_skills_override_defaults(self):
        custom = [{"id": "translate", "name": "Translate", "description": "Translate text"}]
        card = build_mars_agent_card("MARS", "http://localhost:7433/a2a", skills=custom)
        assert card["skills"] == custom

    def test_trailing_slash_stripped_from_base_url(self):
        card = build_mars_agent_card("MARS", "http://localhost:7433/a2a/")
        assert card["url"] == "http://localhost:7433/a2a/"

    def test_description_and_version_set(self):
        card = build_mars_agent_card(
            "MARS", "http://localhost:7433/a2a",
            description="Test node", version="2.0.0",
        )
        assert card["description"] == "Test node"
        assert card["version"] == "2.0.0"


# ── _extract_text ─────────────────────────────────────────────────────────────

class TestExtractText:
    def test_none_returns_placeholder(self):
        assert _extract_text(None) == "(no response)"

    def test_plain_string(self):
        assert _extract_text("hello") == "hello"

    def test_task_with_artifacts(self):
        result = {
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "reply from agent"}]}],
        }
        assert _extract_text(result) == "reply from agent"

    def test_task_with_history(self):
        result = {
            "status": {"state": "completed"},
            "artifacts": [],
            "history": [
                {"role": "user", "parts": [{"kind": "text", "text": "user msg"}]},
                {"role": "agent", "parts": [{"kind": "text", "text": "agent reply"}]},
            ],
        }
        assert _extract_text(result) == "agent reply"

    def test_direct_message_result(self):
        result = {
            "role": "agent",
            "parts": [{"kind": "text", "text": "direct reply"}],
        }
        assert _extract_text(result) == "direct reply"

    def test_failed_task_returns_error(self):
        result = {
            "status": {"state": "failed", "message": "something went wrong"},
        }
        assert "something went wrong" in _extract_text(result)

    def test_empty_dict_returns_json(self):
        result = {"unknown": "field"}
        out = _extract_text(result)
        assert isinstance(out, str)


# ── _parts_to_texts ───────────────────────────────────────────────────────────

class TestPartsToTexts:
    def test_empty_list(self):
        assert _parts_to_texts([]) == []

    def test_extracts_text_parts(self):
        containers = [{"parts": [{"kind": "text", "text": "hello"}, {"kind": "file", "text": "skip"}]}]
        result = _parts_to_texts(containers)
        assert result == ["hello"]

    def test_skips_non_text_parts(self):
        containers = [{"parts": [{"kind": "image", "data": "..."}]}]
        assert _parts_to_texts(containers) == []

    def test_multiple_containers(self):
        containers = [
            {"parts": [{"kind": "text", "text": "a"}]},
            {"parts": [{"kind": "text", "text": "b"}]},
        ]
        assert _parts_to_texts(containers) == ["a", "b"]


# ── A2AAdapter ────────────────────────────────────────────────────────────────

SAMPLE_CARD = {
    "name": "Remote MARS",
    "description": "A remote MARS node",
    "url": "http://remote:7433/a2a/",
    "version": "1.0.0",
    "skills": [{"id": "chat", "name": "Chat", "description": "Chat", "tags": []}],
    "capabilities": {},
}


def _make_mock_response(data: dict):
    """Build a MagicMock that behaves like an httpx response."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = data
    return mock_resp


class _MockHttpxClient:
    """Fake httpx.AsyncClient usable as async context manager."""

    def __init__(self, get_data=None, post_data=None, **kwargs):
        self._get_data = get_data
        self._post_data = post_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, url, **kwargs):
        return _make_mock_response(self._get_data or SAMPLE_CARD)

    async def post(self, url, **kwargs):
        return _make_mock_response(self._post_data or {})


@pytest.fixture
def mock_http_get():
    """Patch httpx.AsyncClient to return a fake Agent Card on GET."""
    with patch("httpx.AsyncClient", lambda **kwargs: _MockHttpxClient(get_data=SAMPLE_CARD)):
        yield


@pytest.fixture
def mock_http_post():
    """Patch httpx.AsyncClient to return a fake JSON-RPC A2A result on POST."""
    post_resp = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "id": "task-1",
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": "pong"}]}],
        },
    }
    with patch("httpx.AsyncClient",
               lambda **kwargs: _MockHttpxClient(get_data=SAMPLE_CARD, post_data=post_resp)):
        yield


class TestA2AAdapter:
    @pytest.mark.asyncio
    async def test_start_fetches_agent_card(self, mock_http_get):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        card = await adapter.start()
        assert isinstance(card, AgentCard)
        assert card.name == "Remote MARS"
        assert len(card.skills) == 1
        assert card.skills[0].id == "chat"

    @pytest.mark.asyncio
    async def test_skills_property(self, mock_http_get):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        await adapter.start()
        assert adapter.skills == ["chat"]

    @pytest.mark.asyncio
    async def test_skills_empty_before_start(self):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        assert adapter.skills == []

    @pytest.mark.asyncio
    async def test_call_sends_rpc_and_returns_text(self, mock_http_get, mock_http_post):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        await adapter.start()
        result = await adapter.call("ping")
        assert result == "pong"

    @pytest.mark.asyncio
    async def test_call_without_start_raises(self):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        with pytest.raises(RuntimeError, match="not started"):
            await adapter.call("ping")

    @pytest.mark.asyncio
    async def test_call_structured_serialises_args(self, mock_http_get, mock_http_post):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        await adapter.start()
        result = await adapter.call_structured("summarise", {"text": "long text"})
        assert result == "pong"

    @pytest.mark.asyncio
    async def test_stop_is_noop(self, mock_http_get):
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        await adapter.start()
        await adapter.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_rpc_error_raises_runtime_error(self, mock_http_get):
        error_resp = {
            "jsonrpc": "2.0",
            "id": "1",
            "error": {"code": -32603, "message": "internal error"},
        }
        adapter = A2AAdapter("a2a.remote@1", "http://remote:7433")
        await adapter.start()
        with patch("httpx.AsyncClient",
                   lambda **kwargs: _MockHttpxClient(get_data=SAMPLE_CARD, post_data=error_resp)):
            with pytest.raises(RuntimeError, match="internal error"):
                await adapter.call("ping")
