from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re as _re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from mars.client.providers.base import LLMMessage, ToolSpec
from mars.client.providers.registry import get_provider
from mars.runtime.services.service_utils import parse_server, send_json
from mars.constants import (
    AGENT_TYPE_LLM,
    DEFAULT_LLM_SKILLS,
    MCP_BUFFER_SIZE,
    MAX_TOOL_ITERATIONS,
    TOOL_CALL_TIMEOUT,
    TOOL_ARGS_KEY,
    TOOL_KEY,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful agent in the MARS multi-agent runtime. "
    "Reply concisely and directly to the human or agent who contacted you. "
    "Use the available tools whenever they help you answer accurately. "
    "When a tool returns a result, interpret it and respond in natural language — "
    "do NOT return raw JSON or tool output verbatim."
)


@dataclass
class _ServiceTool:
    """One MCP tool on a service agent, exposed to the LLM."""
    agent_id: str
    # tool_name is the MCP tool name (e.g. "get_time", "search_repositories").
    # Falls back to a sanitised agent_id when no MCP schema was provided.
    tool_name: str
    description: str
    # Real MCP input_schema when available; generic single-string fallback otherwise.
    input_schema: dict[str, Any]
    # Extra skill aliases for routing (not sent to LLM)
    skills: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return _re.sub(r"[^a-zA-Z0-9_]", "_", self.tool_name)

    @property
    def parameters(self) -> dict[str, Any]:
        return self.input_schema

    @staticmethod
    def _generic_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The request or query to send to the service.",
                }
            },
            "required": ["request"],
        }

    @classmethod
    def from_spawn(cls, agent_id: str, skills: list[str], tool_schemas: list[dict]) -> "list[_ServiceTool]":
        """Build one _ServiceTool per MCP tool schema, or a generic fallback."""
        if tool_schemas:
            return [
                cls(
                    agent_id=agent_id,
                    tool_name=ts["name"],
                    description=ts.get("description", f"Tool '{ts['name']}' on {agent_id}."),
                    input_schema=ts.get("input_schema") or cls._generic_schema(),
                    skills=skills,
                )
                for ts in tool_schemas
            ]
        # No schemas — create one generic tool named after the primary skill
        primary = skills[0] if skills else agent_id
        extras = ", ".join(skills[1:6]) if len(skills) > 1 else ""
        desc = f"Service tool '{primary}' (agent: {agent_id})."
        if extras:
            desc += f" Also handles: {extras}."
        return [cls(
            agent_id=agent_id,
            tool_name=primary,
            description=desc,
            input_schema=cls._generic_schema(),
            skills=skills,
        )]


async def run_llm_agent(
    *,
    server: str,
    provider: str,
    model: str | None = None,
    key: str | None = None,
    host: str | None = None,
    name: str | None = None,
    mock_tool_name: str | None = None,
    mock_tool_request: str | None = None,
) -> None:
    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    if key:
        kwargs["api_key"] = key
    if host:
        kwargs["host"] = host
    if provider in ("mock-tool",):
        if mock_tool_name:
            kwargs["tool_name"] = mock_tool_name
        if mock_tool_request:
            kwargs["tool_request"] = mock_tool_request
    llm = get_provider(provider, **kwargs)

    host_name, port = parse_server(server)
    reader, writer = await asyncio.open_connection(host_name, port, limit=MCP_BUFFER_SIZE)

    base_name = name or f"llm.{provider}" + (f".{llm.model}" if getattr(llm, "model", "") else "")
    hello = {
        "t": "hello",
        "role": "agent",
        "name": base_name,
        "agent_type": AGENT_TYPE_LLM,
        "model": getattr(llm, "model", model or ""),
        "vendor": getattr(llm, "provider_name", provider),
        "skills": DEFAULT_LLM_SKILLS,
    }
    await send_json(writer, hello)

    agent_id = base_name
    histories: dict[str, list[LLMMessage]] = defaultdict(
        lambda: [LLMMessage(role="system", content=_SYSTEM_PROMPT)]
    )

    # tool_name → _ServiceTool  (one entry per MCP tool, many tools per agent possible)
    _service_tools: dict[str, _ServiceTool] = {}
    # agent_id → set[tool_name]  (so we can remove all tools when an agent despawns)
    _tools_by_agent: dict[str, set[str]] = defaultdict(set)

    # Pending tool-call futures: call_id → Future[str]  (resolved when service replies)
    # Also maps agent_id → call_id so incoming replies can be matched.
    _pending: dict[str, asyncio.Future[str]] = {}    # call_id → future
    _call_by_agent: dict[str, str] = {}              # service agent_id → call_id

    # One lock per sender — prevents concurrent requests from the same human from
    # interleaving history entries while still allowing the read loop to stay live.
    _locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _register_agent_tools(cid: str, skills: list[str], tool_schemas: list[dict]) -> None:
        tools = _ServiceTool.from_spawn(cid, skills, tool_schemas)
        for t in tools:
            _service_tools[t.name] = t
            _tools_by_agent[cid].add(t.name)

    def _deregister_agent(cid: str) -> None:
        for tname in _tools_by_agent.pop(cid, set()):
            _service_tools.pop(tname, None)

    def _tool_specs() -> list[ToolSpec] | None:
        if not _service_tools or not getattr(llm, "supports_tools", True):
            return None
        return list(_service_tools.values())  # type: ignore[return-value]

    async def _call_tool(tool: _ServiceTool, args: dict[str, Any]) -> str:
        """Send a structured tool call to the service agent, wait for its reply."""
        call_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        _pending[call_id] = fut
        _call_by_agent[tool.agent_id] = call_id

        # Use the structured envelope so the server can route to the right MCP tool
        # with the right arguments, regardless of how many parameters it has.
        envelope = json.dumps({TOOL_KEY: tool.tool_name, TOOL_ARGS_KEY: args})
        await send_json(writer, {"t": "msg", "target": tool.agent_id, "text": envelope})
        try:
            return await asyncio.wait_for(fut, timeout=TOOL_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"(tool '{tool.agent_id}/{tool.tool_name}' did not respond within {TOOL_CALL_TIMEOUT}s)"
        finally:
            _pending.pop(call_id, None)
            _call_by_agent.pop(tool.agent_id, None)

    async def _run_to_completion(from_id: str) -> str:
        """Run the LLM tool-call loop until the model returns a final text reply."""
        history = histories[from_id]
        for _ in range(MAX_TOOL_ITERATIONS):  # guard against infinite tool-call loops
            tools = _tool_specs()
            try:
                response = await llm.complete(history, tools=tools)
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM agent %s failed", agent_id)
                return f"Error: {exc}"

            # No tool calls → done, return the text
            if not response.tool_calls:
                reply = str(response.content or "")
                history.append(LLMMessage(role="assistant", content=reply))
                return reply

            # Record the assistant turn with its tool-call requests
            history.append(LLMMessage(role="assistant", content=response.content, tool_calls=response.tool_calls))

            # Dispatch each tool call and collect results
            for tc in response.tool_calls:
                tc_id   = tc.get("id", str(uuid.uuid4()))
                fn_name = tc.get("function", {}).get("name", "")
                try:
                    args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except Exception:
                    args = {}

                tool = _service_tools.get(fn_name)
                if tool is None:
                    result_text = f"Unknown tool: {fn_name}"
                else:
                    result_text = await _call_tool(tool, args)

                history.append(LLMMessage(
                    role="tool",
                    content=result_text,
                    tool_call_id=tc_id,
                    name=fn_name,
                ))

        return "(max tool-call iterations reached)"

    async def _handle_human_message(from_id: str) -> None:
        """Process a human's message in a background task.

        Running this as a task (not inline) keeps the main read loop alive
        so it can receive tool-result replies that resolve pending futures.
        """
        await send_json(writer, {"t": "fsm", "fsm_state": "THINKING"})
        async with _locks[from_id]:
            reply_text = await _run_to_completion(from_id)
        await send_json(writer, {"t": "fsm", "fsm_state": "IDLE"})
        await send_json(writer, {"t": "msg", "target": from_id, "text": reply_text})

    try:
        while not reader.at_eof():
            raw = await reader.readline()
            if not raw:
                break
            try:
                ev = json.loads(raw.decode("utf-8"))
            except Exception:
                continue

            etype = ev.get("t")

            if etype == "welcome":
                agent_id = str(ev.get("your_id") or agent_id)
                continue

            # Track service agents joining/leaving — they become tools
            if etype == "spawn":
                cid          = str(ev.get("agent_id") or "")
                crole        = str(ev.get("agent_type") or "")
                skills       = list(ev.get("skills") or [])
                tool_schemas = list(ev.get("tool_schemas") or [])
                if crole == "ServiceAgent" and cid and cid != agent_id:
                    _register_agent_tools(cid, skills, tool_schemas)
                continue

            if etype == "despawn":
                cid = str(ev.get("agent_id") or "")
                _deregister_agent(cid)
                continue

            if etype == "client_connect":
                cid    = str(ev.get("name") or "")
                crole  = str(ev.get("role") or "")
                skills = list(ev.get("skills") or [])
                if crole == "agent" and cid and cid != agent_id:
                    _register_agent_tools(cid, skills, [])
                continue

            if etype == "client_disconnect":
                cid = str(ev.get("name") or "")
                _deregister_agent(cid)
                continue

            if etype != "msg":
                continue

            from_id = str(ev.get("from") or "")
            text    = str(ev.get("text") or "")
            if not from_id:
                continue

            # Reply from a service agent resolves a pending tool-call future
            if from_id in _call_by_agent:
                call_id = _call_by_agent[from_id]
                fut = _pending.get(call_id)
                if fut is not None and not fut.done():
                    fut.set_result(text)
                continue

            # Message from a human — run the full tool-call loop in a background
            # task so this read loop stays live to receive tool-result replies.
            history = histories[from_id]
            history.append(LLMMessage(role="user", content=text))
            asyncio.create_task(_handle_human_message(from_id))

    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mars-llm-wire-agent")
    parser.add_argument("--server", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--mock-tool-name", default=None, dest="mock_tool_name")
    parser.add_argument("--mock-tool-request", default=None, dest="mock_tool_request")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    asyncio.run(
        run_llm_agent(
            server=args.server,
            provider=args.provider,
            model=args.model,
            key=args.key,
            host=args.host,
            name=args.name,
            mock_tool_name=args.mock_tool_name,
            mock_tool_request=args.mock_tool_request,
        )
    )


if __name__ == "__main__":
    main()
