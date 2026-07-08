from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import re as _re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from mars.server.services.llm.base import LLMMessage, ToolSpec
from mars.server.services.registry import get_service
from mars.common.constants import (
    AGENT_TYPE_LLM,
    DEFAULT_LLM_SKILLS,
    MAX_TOOL_ITERATIONS,
    MCP_BUFFER_SIZE,
    TOOL_ARGS_KEY,
    TOOL_CALL_TIMEOUT,
    TOOL_KEY,
)
from mars.common.wire import iter_frames
from mars.server.services.service_utils import parse_server, send_json

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
    def from_spawn(cls, agent_id: str, skills: list[str], tool_schemas: list[dict]) -> list[_ServiceTool]:
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
    system_prompt: str | None = None,
    kickoff: str | None = None,
    mock_tool_name: str | None = None,
    mock_tool_request: str | None = None,
    thinking: bool = False,
    cache_prompts: bool | None = None,
    max_tokens: int | None = None,
    allowed_skills: list[str] | None = None,
) -> None:
    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    if key:
        kwargs["api_key"] = key
    if host:
        kwargs["host"] = host
    # max_tokens is the common denominator across providers: every adapter
    # (Anthropic and the OpenAI-compatible copilot/ollama) spreads default_params
    # into each completion call, so route it there rather than via a
    # provider-specific constructor argument.
    if max_tokens is not None:
        kwargs["default_params"] = {"max_tokens": max_tokens}
    # thinking + prompt caching have no OpenAI-compatible equivalent, so they are
    # Anthropic-only — simply absent (not an error) for copilot/ollama.
    if provider.lower().strip() in ("anthropic", "claude"):
        if thinking:
            kwargs["thinking"] = True
        kwargs["cache_prompts"] = True if cache_prompts is None else cache_prompts
    if provider in ("mock-tool",):
        if mock_tool_name:
            kwargs["tool_name"] = mock_tool_name
        if mock_tool_request:
            kwargs["tool_request"] = mock_tool_request
    llm = get_service(provider, **kwargs)

    # Role isolation: when an allow-list is supplied, only tools whose MCP name
    # or any routing skill is listed are advertised to this agent.  Empty/None
    # preserves the default of exposing every registered tool.
    _allowed: set[str] | None = {s for s in (allowed_skills or []) if s} or None

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
    _effective_system_prompt = system_prompt or _SYSTEM_PROMPT
    histories: dict[str, list[LLMMessage]] = defaultdict(
        lambda: [LLMMessage(role="system", content=_effective_system_prompt)]
    )

    # tool_name → _ServiceTool  (one entry per MCP tool, many tools per agent possible)
    _service_tools: dict[str, _ServiceTool] = {}
    # agent_id → set[tool_name]  (so we can remove all tools when an agent despawns)
    _tools_by_agent: dict[str, set[str]] = defaultdict(set)

    # Pending tool-call futures: call_id → Future[str]  (resolved when service replies)
    # Also maps agent_id → call_id so incoming replies can be matched.
    _pending: dict[str, asyncio.Future[str]] = {}    # call_id → future
    _call_by_agent: dict[str, str] = {}              # service agent_id → call_id

    # Global serialization lock: only ONE _run_to_completion loop may run at a time.
    # Per-sender locks caused a race: concurrent loops for different senders both wrote
    # to _call_by_agent[same_service], causing one loop's tool-call future to be stolen
    # by the other → the victim loop timed out but had already appended
    # assistant+tool_calls to history without a matching tool result → OpenAI 400.
    _global_lock = asyncio.Lock()

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
        tools = list(_service_tools.values())
        if _allowed is not None:
            tools = [
                t for t in tools
                if t.tool_name in _allowed or any(s in _allowed for s in t.skills)
            ]
            if not tools:
                return None
        return tools  # type: ignore[return-value]

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
        except TimeoutError:
            return f"(tool '{tool.agent_id}/{tool.tool_name}' did not respond within {TOOL_CALL_TIMEOUT}s)"
        finally:
            _pending.pop(call_id, None)
            _call_by_agent.pop(tool.agent_id, None)

    def _repair_history(history: list[LLMMessage]) -> bool:
        """Remove the last assistant+tool_calls entry (and anything after it) if it
        lacks matching tool-result messages.  Returns True if something was removed."""
        for i in range(len(history) - 1, -1, -1):
            msg = history[i]
            if msg.role == "assistant" and msg.tool_calls:
                expected_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
                found_ids = {
                    m.tool_call_id for m in history[i + 1:]
                    if m.role == "tool" and m.tool_call_id
                }
                if not expected_ids.issubset(found_ids):
                    logger.warning(
                        "LLM agent %s: repairing broken history — removing entry at index %d "
                        "(missing tool results for %s)",
                        agent_id, i, expected_ids - found_ids,
                    )
                    del history[i:]
                    return True
        return False

    async def _run_to_completion(from_id: str) -> str:
        """Run the LLM tool-call loop until the model returns a final text reply."""
        history = histories[from_id]
        for _ in range(MAX_TOOL_ITERATIONS):  # guard against infinite tool-call loops
            tools = _tool_specs()
            try:
                response = await llm.complete(history, tools=tools)
            except Exception as exc:  # noqa: BLE001
                exc_str = str(exc)
                # Recover from history corruption: if OpenAI rejects because an
                # assistant+tool_calls message is not followed by tool results,
                # strip the broken entry and retry once so the session can recover.
                if "tool_call" in exc_str and "tool messages" in exc_str:
                    if _repair_history(history):
                        logger.warning("LLM agent %s: retrying after history repair", agent_id)
                        continue
                logger.exception("LLM agent %s failed", agent_id)
                return f"Error: {exc}"

            # No tool calls → done, return the text
            if not response.tool_calls:
                reply = str(response.content or "")
                history.append(LLMMessage(role="assistant", content=reply))
                return reply

            # Record the assistant turn with its tool-call requests.  Carry any
            # extended/interleaved thinking (with its signature) so providers
            # like Anthropic can replay it on the next round — without it the
            # reasoning chain is broken across tool calls.
            history.append(LLMMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
                thinking=response.thinking,
                thinking_signature=response.thinking_signature,
            ))

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

    async def _handle_human_message(from_id: str, text: str) -> None:
        """Process a human's message in a background task.

        Running this as a task (not inline) keeps the main read loop alive
        so it can receive tool-result replies that resolve pending futures.

        The global lock serialises ALL _run_to_completion calls regardless of
        sender.  Per-sender locks caused a race: concurrent loops for different
        senders (e.g. "system" and "svc.coordinator") both wrote to the shared
        _call_by_agent dict, causing tool-result futures to be stolen and
        leaving history with assistant+tool_calls without matching tool results,
        which OpenAI rejects with HTTP 400.
        """
        await send_json(writer, {"t": "fsm", "fsm_state": "THINKING"})
        async with _global_lock:
            histories[from_id].append(LLMMessage(role="user", content=text))
            reply_text = await _run_to_completion(from_id)
        await send_json(writer, {"t": "fsm", "fsm_state": "IDLE"})
        # A kickoff is delivered with from_id == "system", which is not a routable
        # participant — sending the reply there silently drops it. If the kickoff
        # failed (e.g. an unsupported-model error), surface it loudly so the
        # operator/coordinator can see and recover instead of stalling silently.
        if from_id == "system":
            if reply_text.startswith("Error:"):
                logger.error(
                    "LLM agent %s: kickoff failed — %s. The phase will not progress; "
                    "the coordinator must reset_phase + re-spawn (or fix the model).",
                    agent_id, reply_text,
                )
                print(f"[{agent_id}] KICKOFF FAILED: {reply_text}", file=sys.stderr, flush=True)
            return
        await send_json(writer, {"t": "msg", "target": from_id, "text": reply_text})

    try:
        async for ev in iter_frames(reader):

            etype = ev.get("t")

            if etype == "welcome":
                agent_id = str(ev.get("your_id") or agent_id)
                if kickoff:
                    # Fire the kickoff as if a "system" user sent it.
                    # All service tools are already registered by this point
                    # (spawn events arrive before welcome in the server's hello flow).
                    asyncio.create_task(_handle_human_message("system", kickoff))
                continue

            # Track service agents joining/leaving — they become tools
            if etype == "spawn":
                cid          = str(ev.get("agent_id") or "")
                crole        = str(ev.get("agent_type") or "")
                skills       = list(ev.get("skills") or [])
                tool_schemas = list(ev.get("tool_schemas") or [])
                if crole == "Provider" and cid and cid != agent_id:
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
            # NOTE: history.append happens INSIDE _handle_human_message under the
            # per-sender lock, NOT here.  Appending here would race with an
            # in-flight tool-call loop and corrupt the message sequence.
            asyncio.create_task(_handle_human_message(from_id, text))

    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mars-llm-wire-agent")
    parser.add_argument("--server", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--system-prompt", default=None, dest="system_prompt",
                        help="Override the default system prompt for this agent instance.")
    parser.add_argument("--kickoff", default=None,
                        help="Initial message sent automatically after the agent connects.")
    parser.add_argument("--mock-tool-name", default=None, dest="mock_tool_name")
    parser.add_argument("--mock-tool-request", default=None, dest="mock_tool_request")
    # --max-tokens applies to every provider; --thinking / --cache-prompts are
    # Anthropic-only and are no-ops elsewhere.
    parser.add_argument("--thinking", action="store_true", default=False,
                        help="Enable Anthropic extended thinking (model-appropriate config).")
    parser.add_argument("--cache-prompts", action=argparse.BooleanOptionalAction,
                        default=None, dest="cache_prompts",
                        help="Toggle Anthropic prompt caching (default: on for Claude).")
    parser.add_argument("--max-tokens", type=int, default=None, dest="max_tokens",
                        help="Max output tokens per completion (all providers).")
    # Role isolation: comma-separated allow-list of tool names / skills.
    parser.add_argument("--skills", default=None,
                        help="Comma-separated tool/skill allow-list; restricts which "
                             "service tools this agent may call (default: all).")
    args = parser.parse_args(argv)

    allowed_skills = (
        [s.strip() for s in args.skills.split(",") if s.strip()]
        if args.skills else None
    )

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")

    asyncio.run(
        run_llm_agent(
            server=args.server,
            provider=args.provider,
            model=args.model,
            key=args.key,
            host=args.host,
            name=args.name,
            system_prompt=args.system_prompt,
            kickoff=args.kickoff,
            mock_tool_name=args.mock_tool_name,
            mock_tool_request=args.mock_tool_request,
            thinking=args.thinking,
            cache_prompts=args.cache_prompts,
            max_tokens=args.max_tokens,
            allowed_skills=allowed_skills,
        )
    )


if __name__ == "__main__":
    main()
