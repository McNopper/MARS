from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re as _re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from mars.providers.base import LLMMessage, ToolSpec
from mars.providers.registry import get_provider
from mars.services.service_utils import parse_server, send_json

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful agent in the MARS multi-agent runtime. "
    "Reply concisely and directly to the human or agent who contacted you. "
    "Use the available tools whenever they help you answer accurately. "
    "When a tool returns a result, interpret it and respond in natural language — "
    "do NOT return raw JSON or tool output verbatim."
)

_TOOL_CALL_TIMEOUT = 30.0  # seconds to wait for a service-agent tool result


@dataclass
class _ServiceTool:
    """A service agent exposed as an LLM tool."""
    agent_id: str
    skills: list[str]

    @property
    def name(self) -> str:
        # Use the primary skill (first in list) as the function name — it is the
        # MCP tool name (e.g. "get_time", "solve_math").  Fall back to the
        # sanitised agent_id only when skills are absent.
        primary = self.skills[0] if self.skills else ""
        if primary:
            return _re.sub(r"[^a-zA-Z0-9_]", "_", primary)
        return _re.sub(r"[^a-zA-Z0-9_]", "_", self.agent_id)

    @property
    def description(self) -> str:
        extras = ", ".join(self.skills[1:6]) if len(self.skills) > 1 else ""
        base = f"Service tool '{self.name}' (agent: {self.agent_id})."
        if extras:
            base += f" Also handles: {extras}."
        return base

    @property
    def parameters(self) -> dict[str, Any]:
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


async def run_llm_agent(
    *,
    server: str,
    provider: str,
    model: str | None = None,
    key: str | None = None,
    host: str | None = None,
    name: str | None = None,
) -> None:
    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    if key:
        kwargs["api_key"] = key
    if host:
        kwargs["host"] = host
    llm = get_provider(provider, **kwargs)

    host_name, port = parse_server(server)
    reader, writer = await asyncio.open_connection(host_name, port, limit=16 * 1024 * 1024)

    base_name = name or f"llm.{provider}" + (f".{llm.model}" if getattr(llm, "model", "") else "")
    hello = {
        "t": "hello",
        "role": "agent",
        "name": base_name,
        "agent_type": "LLMAgent",
        "model": getattr(llm, "model", model or ""),
        "vendor": getattr(llm, "provider_name", provider),
        "skills": ["llm", "chat", "reasoning"],
    }
    await send_json(writer, hello)

    agent_id = base_name
    histories: dict[str, list[LLMMessage]] = defaultdict(
        lambda: [LLMMessage(role="system", content=_SYSTEM_PROMPT)]
    )

    # Service agents discovered via client_connect events → used as tools
    _service_tools: dict[str, _ServiceTool] = {}  # agent_id → tool

    # Pending tool-call futures: call_id → Future[str]  (resolved when service replies)
    # Also maps agent_id → call_id so incoming replies can be matched.
    _pending: dict[str, asyncio.Future[str]] = {}    # call_id → future
    _call_by_agent: dict[str, str] = {}              # service agent_id → call_id

    # One lock per sender — prevents concurrent requests from the same human from
    # interleaving history entries while still allowing the read loop to stay live.
    _locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _tool_specs() -> list[ToolSpec] | None:
        if not _service_tools or not getattr(llm, "supports_tools", True):
            return None
        return list(_service_tools.values())  # type: ignore[return-value]

    async def _call_tool(tool: _ServiceTool, request: str) -> str:
        """Send a request to the service agent, wait for its reply."""
        call_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        _pending[call_id] = fut
        _call_by_agent[tool.agent_id] = call_id
        await send_json(writer, {"t": "msg", "target": tool.agent_id, "text": request})
        try:
            return await asyncio.wait_for(fut, timeout=_TOOL_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"(tool '{tool.agent_id}' did not respond within {_TOOL_CALL_TIMEOUT}s)"
        finally:
            _pending.pop(call_id, None)
            _call_by_agent.pop(tool.agent_id, None)

    async def _run_to_completion(from_id: str) -> str:
        """Run the LLM tool-call loop until the model returns a final text reply."""
        history = histories[from_id]
        for _ in range(8):  # guard against infinite tool-call loops
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
                request_text = args.get("request", str(args))

                # Find the matching service tool by sanitised name
                tool = next((t for t in _service_tools.values() if t.name == fn_name), None)
                if tool is None:
                    result_text = f"Unknown tool: {fn_name}"
                else:
                    result_text = await _call_tool(tool, request_text)

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
        async with _locks[from_id]:
            reply_text = await _run_to_completion(from_id)
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
                cid    = str(ev.get("agent_id") or "")
                crole  = str(ev.get("agent_type") or "")
                skills = list(ev.get("skills") or [])
                if crole == "ServiceAgent" and cid and cid != agent_id:
                    _service_tools[cid] = _ServiceTool(agent_id=cid, skills=skills)
                continue

            if etype == "despawn":
                cid = str(ev.get("agent_id") or "")
                _service_tools.pop(cid, None)
                continue

            if etype == "client_connect":
                cid    = str(ev.get("name") or "")
                crole  = str(ev.get("role") or "")
                skills = list(ev.get("skills") or [])
                if crole == "agent" and cid and cid != agent_id:
                    _service_tools[cid] = _ServiceTool(agent_id=cid, skills=skills)
                continue

            if etype == "client_disconnect":
                cid = str(ev.get("name") or "")
                _service_tools.pop(cid, None)
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
        )
    )


if __name__ == "__main__":
    main()
