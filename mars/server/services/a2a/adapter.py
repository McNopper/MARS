"""MARS A2A (Agent2Agent) client adapter.

Calls a remote A2A-compliant agent over HTTP using JSON-RPC 2.0.
Fetches the Agent Card from ``/.well-known/agent.json`` and sends
requests via the ``message/send`` method.

A2A complements MCP: MCP is agent↔tool (stdio subprocess), A2A is
agent↔agent (HTTP peer).  This adapter mirrors the MCPAdapter interface
so the rest of the server can treat both identically.

Reference: https://a2a-protocol.org/latest/specification/
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from mars.common.constants import (
    A2A_CARD_PATH,
    A2A_METHOD_SEND,
    A2A_TASK_STATE_FAILED,
    A2A_TIMEOUT,
)

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class A2ASkill:
    """A single capability advertised by a remote A2A agent."""
    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class AgentCard:
    """Agent Card as defined by A2A spec §4.1."""
    name: str
    url: str
    description: str = ""
    version: str = "1.0.0"
    skills: list[A2ASkill] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)


# ── Adapter ───────────────────────────────────────────────────────────────────

class A2AAdapter:
    """HTTP client adapter for an external A2A-compliant agent.

    Usage::

        adapter = A2AAdapter("svc.planner", "http://planner-host:8080")
        card = await adapter.start()        # fetches Agent Card
        result = await adapter.call("plan a trip to Paris")
        await adapter.stop()                # no-op for HTTP adapters

    The ``call`` and ``call_structured`` methods mirror ``MCPAdapter`` so the
    server can handle MCP and A2A agents interchangeably.
    """

    def __init__(self, agent_id: str, base_url: str) -> None:
        self.agent_id = agent_id
        self._base_url = base_url.rstrip("/")
        self._card: AgentCard | None = None

    # ── Public interface (mirrors MCPAdapter) ─────────────────────────────────

    @property
    def card(self) -> AgentCard | None:
        return self._card

    @property
    def skills(self) -> list[str]:
        """Skill IDs advertised by the remote agent's Agent Card."""
        if self._card is None:
            return []
        return [s.id for s in self._card.skills]

    async def start(self) -> AgentCard:
        """Fetch the Agent Card and return it.  Must be called before ``call``."""
        self._card = await self._fetch_card()
        return self._card

    async def call(self, request: str, tool_name: str | None = None) -> str:
        """Send a plain-text request via A2A ``message/send`` and return the reply.

        *tool_name* is accepted for API compatibility with MCPAdapter but is
        ignored — A2A routes by capability, not by explicit tool name.
        """
        params = {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": request}],
            }
        }
        result = await self._rpc(A2A_METHOD_SEND, params)
        return _extract_text(result)

    async def call_structured(self, tool_name: str | None, arguments: dict[str, Any]) -> str:
        """Call with pre-built arguments dict.

        Serialises *arguments* to JSON and sends as a text part.
        This maintains API compatibility with MCPAdapter's structured calls.
        """
        text = json.dumps(arguments) if len(arguments) != 1 else next(iter(arguments.values()))
        return await self.call(str(text), tool_name=tool_name)

    async def stop(self) -> None:
        """No persistent connection to close for HTTP adapters."""

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _fetch_card(self) -> AgentCard:
        """GET ``/.well-known/agent.json`` and parse it into an AgentCard."""
        card_url = f"{self._base_url}{A2A_CARD_PATH}"
        async with httpx.AsyncClient(timeout=A2A_TIMEOUT) as client:
            resp = await client.get(card_url)
            resp.raise_for_status()
            data = resp.json()

        skills = [
            A2ASkill(
                id=s.get("id", ""),
                name=s.get("name", s.get("id", "")),
                description=s.get("description", ""),
                tags=list(s.get("tags", [])),
            )
            for s in data.get("skills", [])
        ]
        return AgentCard(
            name=data.get("name", self.agent_id),
            url=data.get("url", self._base_url + "/"),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            skills=skills,
            capabilities=dict(data.get("capabilities", {})),
        )

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC 2.0 request to the agent's A2A endpoint."""
        if self._card is None:
            raise RuntimeError("A2AAdapter not started — call start() first")
        endpoint = self._card.url.rstrip("/")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        async with httpx.AsyncClient(timeout=A2A_TIMEOUT) as client:
            resp = await client.post(
                endpoint,
                content=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()

        if "error" in body:
            err = body["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise RuntimeError(f"A2A error from {self.agent_id}: {msg}")
        return body.get("result")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text(result: Any) -> str:
    """Pull human-readable text out of an A2A ``message/send`` result.

    The result may be a Task (with artifacts) or a direct Message.
    We walk the parts and join all text parts.
    """
    if result is None:
        return "(no response)"

    # Task result — extract from artifacts or latest message
    if isinstance(result, dict):
        # Try artifacts first (completed task)
        status_state = (result.get("status") or {}).get("state", "")
        if status_state in (A2A_TASK_STATE_FAILED,):
            err_msg = (result.get("status") or {}).get("message", "task failed")
            return f"Error: {err_msg}"

        artifacts = result.get("artifacts") or []
        texts = _parts_to_texts(artifacts)
        if texts:
            return "\n".join(texts)

        # Try history (last message from agent)
        history = result.get("history") or []
        for msg in reversed(history):
            if msg.get("role") == "agent":
                texts = _parts_to_texts([msg])
                if texts:
                    return "\n".join(texts)

        # Direct Message result (no task wrapper)
        if "parts" in result or "role" in result:
            texts = _parts_to_texts([result])
            if texts:
                return "\n".join(texts)

        # Fallback: return JSON
        return json.dumps(result, indent=2, default=str)

    return str(result)


def _parts_to_texts(containers: list[Any]) -> list[str]:
    """Collect all text part values from a list of messages / artifacts."""
    out: list[str] = []
    for item in containers:
        if not isinstance(item, dict):
            continue
        for part in item.get("parts", []):
            if not isinstance(part, dict):
                continue
            kind = part.get("kind") or part.get("type", "")
            if kind == "text":
                text = part.get("text", "")
                if text:
                    out.append(text)
    return out


# ── Agent Card builder (for exposing MARS as an A2A server) ───────────────────

def build_mars_agent_card(
    name: str,
    base_url: str,
    *,
    description: str = "MARS multi-agent runtime",
    version: str = "1.0.0",
    skills: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the Agent Card dict that MARS exposes at ``/.well-known/agent.json``.

    The card describes MARS as an A2A server so external agents can discover
    its capabilities and send it tasks.
    """
    default_skills = skills or [
        {"id": "chat", "name": "Chat", "description": "General conversation and reasoning.", "tags": ["chat", "llm"]},
        {
            "id": "reasoning",
            "name": "Reasoning",
            "description": "Multi-step reasoning and problem solving.",
            "tags": ["reasoning", "llm"],
        },
    ]
    return {
        "name": name,
        "description": description,
        "url": base_url.rstrip("/") + "/",
        "version": version,
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": default_skills,
    }
