"""Core TCP router: client sessions and the MARSServer message hub."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


from mars.common.models import (
    DEFAULT_FEDERATION_PORT,
    DEFAULT_PORT,
    A2APeer,
    AgentRecord,
    ChatMessage,
    FeedItem,
    MARSState,
)
from mars.server.audit import MARSAuditLog
from mars.server.service_manager import _launch_provider
from mars.cli.utils import _local_ip, _normalize_agent_type
from mars.common.wire import decode_frame, encode_frame
from mars.server.services.a2a.adapter import A2AAdapter
from mars.server.federation import FederationManager
from mars.server.services.service_adapter import ServiceAdapter
from mars.server.services.mcp.adapter import MCPAdapter
from mars.server.services.registry import get_agent_spec, get_service, list_default_services
from mars.server.services.registry import resolve_command
from mars.server.payloads import _agent_payload

logger = logging.getLogger(__name__)

_CHAT_TARGET_TYPES = {"LLMAgent", "BridgeAgent", "CLIBridgeAgent", "HumanUser"}

# Project root — three levels up from mars/server/server.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class ClientSession:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    addr: str
    current_agent: str | None = None
    name: str = "cli"
    role: str = "human"
    skills: list[str] = field(default_factory=list)
    agent_id: str = ""
    agent_type: str | None = None
    model: str = ""
    vendor: str = ""
    last_sender: str = ""


class MARSServer:
    def __init__(self, state: MARSState) -> None:
        self._state = state
        self._audit: MARSAuditLog | None = None
        self._clients: list[ClientSession] = []
        self._sessions_by_id: dict[str, ClientSession] = {}
        self._builtin_adapters: dict[str, ServiceAdapter] = {}
        self._mcp_adapters: dict[str, MCPAdapter] = {}  # agent_id → MCPAdapter
        self._a2a_adapters: dict[str, A2AAdapter] = {}  # agent_id → A2AAdapter
        self._server_addr: str = ""
        self._server_host: str = "127.0.0.1"
        self._server_port: int = DEFAULT_PORT
        self._spawned_pids: list[int] = []
        self._federation: FederationManager | None = None
        self._state._event_listeners.append(self._broadcast)

    def attach_federation(self, manager: FederationManager) -> None:
        """Register the federation manager so agent lifecycle is propagated to peers."""
        self._federation = manager

    def attach_audit(self, audit: MARSAuditLog) -> None:
        """Attach the audit log so full wire frames are recorded when verbose=True."""
        self._audit = audit

    @staticmethod
    def _service_agent_id(name: str, active: set[str]) -> str:
        return MARSServer._unique_agent_id(f"svc.{name}", active)

    def _service_record(self, agent_id: str, service, *, vendor: str = "builtin") -> AgentRecord:
        tool_schemas = [
            {
                "name": cap.name,
                "description": cap.description,
                "input_schema": cap.input_schema,
            }
            for cap in service.capabilities
        ]
        return AgentRecord(
            agent_id=agent_id,
            agent_type="Provider",
            domain="services",
            platform="local",
            server_addr=self._server_addr,
            fsm_state="—",
            model=getattr(service, "service_id", ""),
            vendor=vendor,
            skills=[cap.name for cap in service.capabilities],
            tool_schemas=tool_schemas,
        )

    async def start_builtin_services(self) -> None:
        """Instantiate builtin services and expose them as virtual service agents."""
        if self._builtin_adapters:
            return

        active = set(self._state.agents.keys()) | set(self._sessions_by_id.keys())
        for name in list_default_services():
            service = get_service(name)
            await service.initialize()
            agent_id = self._service_agent_id(name, active)
            active.add(agent_id)
            adapter = ServiceAdapter(agent_id, service)
            self._builtin_adapters[agent_id] = adapter
            rec = self._service_record(agent_id, service)
            self._state.agents[agent_id] = rec
            self._state._fire(
                {
                    "t": "spawn",
                    "agent_id": agent_id,
                    **_agent_payload(rec, self._state),
                }
            )

    @staticmethod
    def _unique_agent_id(requested: str, active: set[str]) -> str:
        match = re.match(r"^(.+?)@(\d+)$", requested)
        base = match.group(1) if match else requested
        counter = 1
        candidate = f"{base}@{counter}"
        while candidate in active:
            counter += 1
            candidate = f"{base}@{counter}"
        return candidate

    def _spawn_subprocess(self, cmd: list[str]) -> None:
        log_dir = Path.home() / ".mars" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        # Prefer --name arg as log label, fall back to --provider, then last arg
        label = next(
            (cmd[i + 1] for i, a in enumerate(cmd) if a == "--name" and i + 1 < len(cmd)),
            None,
        ) or next(
            (cmd[i + 1] for i, a in enumerate(cmd) if a == "--provider" and i + 1 < len(cmd)),
            cmd[-1],
        )
        label = label.replace("/", "_").replace("\\", "_").replace("-", "_")
        log_file = open(log_dir / f"wire_{label}.log", "a")  # noqa: SIM115
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        self._spawned_pids.append(proc.pid)

    @staticmethod
    def _build_wire_agent_cmd(
        server_addr: str,
        *,
        provider: str,
        model: str | None = None,
        name: str | None = None,
        api_key: str | None = None,
        host: str | None = None,
        system_prompt: str | None = None,
        kickoff: str | None = None,
        thinking: bool = False,
        cache_prompts: bool | None = None,
        max_tokens: str | int | None = None,
        skills: str | list[str] | None = None,
    ) -> list[str]:
        """Build the argv for a ``mars-llm-wire-agent`` subprocess.

        Single source of truth for spawning LLM wire agents — used by
        ``/spawn``, the ``_mars_cmd`` envelope (launcher / coordinator), and
        the server's startup auto-spawn.  ``provider`` may be a bare name
        (``ollama``) or ``provider/model`` (``ollama/qwen3:4b``);
        the model part is used only when ``model`` is not given explicitly.
        ``max_tokens``, ``skills``, ``thinking``, and ``cache_prompts`` apply
        to all providers.
        """
        provider_name, _, model_from_provider = provider.partition("/")
        model_final = str(model) if model else (model_from_provider or "")
        cmd = [
            sys.executable, "-m", "mars.server.services.llm_wire_agent",
            "--server", server_addr,
            "--provider", provider_name,
        ]
        if model_final:
            cmd += ["--model", model_final]
        if name:
            cmd += ["--name", name]
        if api_key:
            cmd += ["--key", api_key]
        if host:
            cmd += ["--host", host]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        if kickoff:
            cmd += ["--kickoff", kickoff]
        if thinking:
            cmd += ["--thinking"]
        if cache_prompts is True:
            cmd += ["--cache-prompts"]
        elif cache_prompts is False:
            cmd += ["--no-cache-prompts"]
        if max_tokens:
            cmd += ["--max-tokens", str(max_tokens)]
        if skills:
            skills_str = ",".join(skills) if isinstance(skills, list) else str(skills)
            if skills_str:
                cmd += ["--skills", skills_str]
        return cmd

    async def start_mcp_agents(self) -> None:
        """Start all free MCP-protocol service agents as stdio subprocesses."""
        from mars.server.services.registry import all_specs
        for spec in all_specs():
            if spec.protocol != "mcp":
                continue
            if spec.cost == "demand":
                continue
            result = await self._spawn_mcp_agent(spec)
            logger.info("MCP agent start result: %s", result)

    async def stop_mcp_agents(self) -> None:
        """Terminate all running MCP adapter processes."""
        for agent_id, adapter in list(self._mcp_adapters.items()):
            with contextlib.suppress(Exception):
                await adapter.stop()
            self._state.agents.pop(agent_id, None)
        self._mcp_adapters.clear()

    def _state_dump(self) -> dict[str, Any]:
        from mars.server.services.registry import service_info
        chats: dict[str, list[dict[str, Any]]] = {}
        for aid, rec in self._state.agents.items():
            chats[aid] = [
                {
                    "ts": msg.ts.isoformat(),
                    "sender": msg.sender,
                    "content": msg.content,
                    "direction": msg.direction,
                }
                for msg in list(rec.chat)
            ]
        running = self._running_services()
        services = [
            {**svc, "running": svc["name"] in running}
            for svc in service_info()
        ]
        return {
            "t": "state",
            "platform_name": self._state.platform_name,
            "current_agent": self._state.current_agent,
            "agents": {aid: _agent_payload(rec, self._state) for aid, rec in self._state.agents.items()},
            "feed": [
                {
                    "ts": item.ts.isoformat(),
                    "event_type": item.event_type,
                    "from_id": item.from_id,
                    "to_id": item.to_id,
                    "snippet": item.snippet,
                    "performative": item.performative,
                }
                for item in list(self._state.feed)
            ],
            "problems": [],
            "chats": chats,
            # Service registry — same data any agent can get via DiscoveryService.
            # Included here so the TUI can render the services panel without
            # bypassing the protocol.
            "services": services,
        }

    def _running_services(self) -> set[str]:
        """Return the set of service names that currently have an active instance.

        Builtins are always running (embedded in the server process).
        LLM/MCP/A2A are running when they have an active session or adapter.
        """
        running: set[str] = set()

        # Builtins are running when their adapters were started by the server.
        for agent_id in self._builtin_adapters:
            parts = agent_id.split(".")
            if len(parts) >= 2:
                running.add(parts[1].split("@")[0])

        # LLM: active wire-agent sessions — agent_id is "llm.<provider>.<model>@N"
        for session in self._clients:
            aid = session.agent_id
            if aid.startswith("llm."):
                parts = aid.split(".")
                if len(parts) >= 2:
                    running.add(parts[1])  # e.g. "ollama", "copilot", "anthropic"

        # MCP: active adapters — key is "svc.<name>@N"
        for aid in self._mcp_adapters:
            parts = aid.split(".")
            if len(parts) >= 2:
                svc_name = parts[1].split("@")[0]
                running.add(svc_name)

        # A2A: active adapters — key is "a2a.<name>@N"
        for aid in self._a2a_adapters:
            parts = aid.split(".")
            if len(parts) >= 2:
                svc_name = parts[1].split("@")[0]
                running.add(svc_name)

        return running

    def _send_to(self, session: ClientSession, ev: dict[str, Any]) -> None:
        try:
            if session.writer.is_closing():
                raise ConnectionError("client closed")
            session.writer.write(encode_frame(ev))
        except Exception:
            with contextlib.suppress(Exception):
                session.writer.close()

    def _broadcast(self, ev: dict[str, Any]) -> None:
        payload = encode_frame(ev)
        dead: list[ClientSession] = []
        for session in list(self._clients):
            try:
                if session.writer.is_closing():
                    raise ConnectionError("client closed")
                session.writer.write(payload)
            except Exception:
                dead.append(session)
        for session in dead:
            if session in self._clients:
                self._clients.remove(session)
            if session.agent_id and self._sessions_by_id.get(session.agent_id) is session:
                self._sessions_by_id.pop(session.agent_id, None)
            with contextlib.suppress(Exception):
                session.writer.close()

    def _record_feed(self, from_id: str, to_id: str, snippet: str, event_type: str = "message") -> None:
        now = datetime.now()
        self._state.feed.appendleft(FeedItem(
            ts=now,
            event_type=event_type,
            from_id=from_id,
            to_id=to_id,
            snippet=snippet,
            performative="INFORM",
        ))
        self._state._fire({
            "t": "feed",
            "ts": now.isoformat(),
            "event_type": event_type,
            "from_id": from_id,
            "to_id": to_id,
            "snippet": snippet,
            "performative": "INFORM",
        })

    async def _register_session(self, session: ClientSession) -> None:
        requested_name = session.name or ("cli-user" if session.role == "human" else "agent")
        active = set(self._state.agents) | set(self._sessions_by_id)
        agent_id = self._unique_agent_id(requested_name, active)
        session.agent_id = agent_id

        if session.role == "human":
            agent_type = "HumanUser"
            domain = "cli"
        else:
            agent_type = _normalize_agent_type(session.agent_type or "Provider")
            domain = "llm" if agent_type == "LLMAgent" else "services"

        rec = AgentRecord(
            agent_id=agent_id,
            agent_type=agent_type,
            domain=domain,
            platform=session.addr,
            server_addr=self._server_addr,
            fsm_state="—",
            model=session.model,
            vendor=session.vendor,
            skills=list(session.skills),
        )
        self._state.agents[agent_id] = rec

        for existing_id, existing_rec in self._state.agents.items():
            if existing_id == agent_id:
                continue
            self._send_to(session, {"t": "spawn", "agent_id": existing_id, **_agent_payload(existing_rec, self._state)})
        self._send_to(session, {"t": "welcome", "your_id": agent_id})

        self._state._fire({"t": "spawn", "agent_id": agent_id, **_agent_payload(rec, self._state)})
        self._clients.append(session)
        self._sessions_by_id[agent_id] = session

        # Send a full state snapshot to human (TUI) sessions so the services
        # panel is populated via the same wire data any agent would receive from
        # DiscoveryService — no privileged sideband.
        if session.role == "human":
            self._send_to(session, self._state_dump())

        # Advertise locally-spawned service/LLM agents to federation peers so
        # they appear as addressable participants on every connected node.
        if self._federation is not None and session.role == "agent":
            self._federation.broadcast_spawn(rec)

        # Switch every connected human to the newly-spawned LLM agent so the CLI
        # opens a bilateral conversation with it directly.
        if agent_type == "LLMAgent":
            for other in list(self._clients):
                if other.role == "human" and other.agent_id and other is not session:
                    self._send_to(other, {"t": "switch", "current_agent": agent_id})

    async def _remove_session(self, session: ClientSession) -> None:
        if session in self._clients:
            self._clients.remove(session)
        if session.agent_id and self._sessions_by_id.get(session.agent_id) is session:
            self._sessions_by_id.pop(session.agent_id, None)
        if session.agent_id and session.agent_id in self._state.agents:
            self._state.agents.pop(session.agent_id, None)
            self._state.agent_roles.pop(session.agent_id, None)
            self._state.agent_behaviours.pop(session.agent_id, None)
            self._state._fire({"t": "despawn", "agent_id": session.agent_id})
            if self._federation is not None and session.role == "agent":
                self._federation.broadcast_despawn(session.agent_id)

    async def _spawn_mcp_agent(self, spec) -> str:
        """Start a single MCP service agent as a stdio subprocess via MCPAdapter."""
        active_ids = set(self._state.agents.keys())
        try:
            workdir_path = _PROJECT_ROOT / "artifacts" / spec.name
            workdir_path.mkdir(parents=True, exist_ok=True)
            cmd_str = spec.command.format(workdir=str(workdir_path))
            command = resolve_command(cmd_str)

            agent_id = self._unique_agent_id(f"svc.{spec.name}", active_ids)
            adapter = MCPAdapter(agent_id, command)
            await adapter.start()
            self._mcp_adapters[agent_id] = adapter
            skills = [t.name for t in adapter.tools] + spec.skills
            tool_schemas = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in adapter.tools
            ]
            rec = AgentRecord(
                agent_id=agent_id,
                vendor="service",
                model=spec.name,
                agent_type="Provider",
                skills=skills,
                tool_schemas=tool_schemas,
            )
            self._state.agents[agent_id] = rec
            self._state._fire({
                "t": "spawn",
                "agent_id": agent_id,
                "name": spec.name,
                "agent_type": "Provider",
                "skills": skills,
                "tool_schemas": tool_schemas,
                "vendor": "service",
                "model": spec.name,
                "description": spec.description,
            })
            logger.info("MCP agent spawned on demand: %s (%s)", agent_id, spec.name)
            return f"Spawned MCP service '{spec.name}' as {agent_id} with {len(adapter.tools)} tool(s)"
        except Exception as exc:
            logger.warning("Could not spawn MCP agent %s: %s", spec.name, exc)
            return f"Failed to spawn '{spec.name}': {exc}"

    async def _spawn_a2a_agent(self, base_url: str, name: str | None = None) -> str:
        """Connect to a remote A2A agent, fetch its Agent Card, and register it."""
        active_ids = set(self._state.agents.keys())
        label = name or base_url.rstrip("/").rsplit("/", 1)[-1] or "a2a-peer"
        agent_id = self._unique_agent_id(f"a2a.{label}", active_ids)
        adapter = A2AAdapter(agent_id, base_url)
        try:
            card = await adapter.start()
        except Exception as exc:
            return f"Failed to connect to A2A agent at {base_url}: {exc}"
        self._a2a_adapters[agent_id] = adapter
        skills = [s.id for s in card.skills]
        rec = AgentRecord(
            agent_id=agent_id,
            vendor="a2a",
            model=card.name,
            agent_type="Provider",
            skills=skills,
        )
        self._state.agents[agent_id] = rec
        # register in a2a_peers for the TUI panel
        self._state.a2a_peers.append(A2APeer(
            agent_id=agent_id,
            url=base_url,
            name=card.name,
            description=card.description,
            skills=skills,
        ))
        self._state._fire({
            "t": "spawn",
            "agent_id": agent_id,
            "name": card.name,
            "agent_type": "Provider",
            "skills": skills,
            "tool_schemas": [],
            "vendor": "a2a",
            "model": card.name,
            "description": card.description,
        })
        logger.info("A2A agent registered: %s → %s (%s)", agent_id, base_url, card.name)
        return f"Connected to A2A agent '{card.name}' at {base_url} as {agent_id}"

    async def _spawn_from_tokens(self, tokens: list[str]) -> str:
        if not tokens:
            return "Usage: /spawn <provider|service> [args]"

        # A2A peer: /spawn a2a <url> [--name <label>]
        if tokens[0] == "a2a":
            if len(tokens) < 2:
                return "Usage: /spawn a2a <url> [--name <label>]"
            url = tokens[1]
            name: str | None = None
            for i, t in enumerate(tokens[2:], start=2):
                if t == "--name" and i + 1 < len(tokens):
                    name = tokens[i + 1]
            return await self._spawn_a2a_agent(url, name)

        spec = get_agent_spec(tokens[0])
        if spec is not None:
            if spec.protocol == "mcp":
                return await self._spawn_mcp_agent(spec)
            pid, _workdir = _launch_provider(spec, self._server_addr, tokens[1:])
            self._spawned_pids.append(pid)
            return f"Spawned provider '{spec.name}' (pid {pid})"

        provider_name = tokens[0]
        model: str | None = None
        agent_name: str | None = None
        api_key: str | None = None
        host: str | None = None
        thinking = False
        cache_prompts: bool | None = None
        max_tokens: str | None = None
        skills: str | None = None
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token == "--name" and index + 1 < len(tokens):
                agent_name = tokens[index + 1]
                index += 2
            elif token == "--key" and index + 1 < len(tokens):
                api_key = tokens[index + 1]
                index += 2
            elif token == "--host" and index + 1 < len(tokens):
                host = tokens[index + 1]
                index += 2
            elif token == "--max-tokens" and index + 1 < len(tokens):
                max_tokens = tokens[index + 1]
                index += 2
            elif token == "--skills" and index + 1 < len(tokens):
                skills = tokens[index + 1]
                index += 2
            elif token == "--thinking":
                thinking = True
                index += 1
            elif token == "--cache-prompts":
                cache_prompts = True
                index += 1
            elif token == "--no-cache-prompts":
                cache_prompts = False
                index += 1
            elif token.startswith("--"):
                index += 1
            else:
                model = token
                index += 1

        cmd = self._build_wire_agent_cmd(
            self._server_addr,
            provider=provider_name,
            model=model,
            name=agent_name,
            api_key=api_key,
            host=host,
            thinking=thinking,
            cache_prompts=cache_prompts,
            max_tokens=max_tokens,
            skills=skills,
        )
        self._spawn_subprocess(cmd)
        return f"Spawned LLM provider '{provider_name}'" + (f" [{model}]" if model else "")

    def _skill_index(self) -> list[dict[str, Any]]:
        """Build a flat skill→agent index from the live agent registry.

        Returns one entry per (skill, agent) pair so a single agent that
        advertises several skills appears once per skill — this is the shape
        documented in AGENTS.md / ARCHITECTURE.md for ``list_skills``.
        """
        entries: list[dict[str, Any]] = []
        for aid, rec in self._state.agents.items():
            for skill in getattr(rec, "skills", []) or []:
                entries.append({
                    "skill": skill,
                    "agent_id": aid,
                    "agent_type": getattr(rec, "agent_type", None) or "Provider",
                })
        entries.sort(key=lambda e: (e["skill"], e["agent_id"]))
        return entries

    async def _fetch_and_send_models(self, session: ClientSession) -> None:
        """Query list_models() for each available LLM provider, send back a 'models' frame."""
        from mars.server.services.registry import REGISTRY, _is_available, get_service
        models: dict[str, list[str]] = {}
        for name, (_mod, _cls, stype, _default, test_only) in REGISTRY.items():
            if stype != "llm" or test_only:
                continue
            if not _is_available(name):
                models[name] = []
                continue
            try:
                svc = get_service(name)
                result = await asyncio.wait_for(svc.list_models(), timeout=5.0)
                models[name] = [m.id for m in result]
            except Exception:
                models[name] = []
        self._send_to(session, {"t": "models", "models": models})

    async def _handle_structured_command(
        self, session: ClientSession, cmd: str, msg: dict[str, Any]
    ) -> None:
        """Handle structured ``{"t":"cmd","cmd":...}`` frames (programmatic clients).

        Unlike ``_handle_command`` (which parses human slash-command *text*), this
        path dispatches on the explicit ``cmd`` field.  Currently supports
        ``list_skills``; unknown structured commands fall back to the text handler
        when a ``text`` field is present, else report an error.
        """
        if cmd == "list_skills":
            self._send_to(session, {"t": "skills", "skills": self._skill_index()})
            return
        if cmd == "get_models":
            asyncio.create_task(self._fetch_and_send_models(session))
            return
        text = str(msg.get("text") or "").strip()
        if text:
            await self._handle_command(session, text)
            return
        self._send_to(
            session,
            {"t": "status", "text": f"Unsupported structured command: {cmd}", "style": "bold yellow"},
        )

    async def _handle_command(self, session: ClientSession, text: str) -> None:
        try:
            parts = shlex.split(text)
        except ValueError as exc:
            self._send_to(session, {"t": "status", "text": str(exc), "style": "bold red"})
            return
        if not parts:
            return
        cmd = parts[0]
        args = parts[1:]
        if cmd == "/spawn":
            status = await self._spawn_from_tokens(args)
            self._send_to(session, {"t": "status", "text": status, "style": "bold cyan"})
        elif cmd == "/stop":
            target_id = args[0] if args else None
            if not target_id:
                self._send_to(session, {"t": "status", "text": "Usage: /stop <agent_id>", "style": "bold yellow"})
                return
            target_session = self._sessions_by_id.get(target_id)
            if target_session:
                await self._remove_session(target_session)
                with contextlib.suppress(Exception):
                    target_session.writer.close()
                self._send_to(session, {"t": "status", "text": f"Stopped '{target_id}'", "style": "bold cyan"})
            elif target_id in self._mcp_adapters:
                adapter = self._mcp_adapters.pop(target_id)
                with contextlib.suppress(Exception):
                    await adapter.stop()
                if target_id in self._state.agents:
                    self._state.agents.pop(target_id, None)
                    self._state._fire({"t": "despawn", "agent_id": target_id})
                self._send_to(
                    session,
                    {"t": "status", "text": f"Stopped MCP agent '{target_id}'", "style": "bold cyan"},
                )
            else:
                self._send_to(
                    session,
                    {"t": "status", "text": f"Agent '{target_id}' not found", "style": "bold yellow"},
                )
        elif cmd == "/switch":
            target_id = args[0] if args else None
            if not target_id:
                self._send_to(session, {"t": "status", "text": "Usage: /switch <agent_id>", "style": "bold yellow"})
                return
            rec = self._state.agents.get(target_id)
            if rec is None or rec.agent_type not in _CHAT_TARGET_TYPES:
                self._send_to(session, {"t": "status", "text": f"'{target_id}' is not a chat target", "style": "bold yellow"})
                return
            session.current_agent = target_id
            self._send_to(session, {"t": "switch", "current_agent": session.current_agent})
        elif cmd == "/federate":
            if self._federation is None:
                self._send_to(session, {"t": "status", "text": "Federation is not enabled on this server", "style": "bold yellow"})
                return
            if not args:
                self._send_to(session, {"t": "status", "text": "Usage: /federate <host>[:port]", "style": "bold yellow"})
                return
            host_arg = args[0]
            if ":" in host_arg:
                host, _, port_s = host_arg.rpartition(":")
                try:
                    port = int(port_s)
                except ValueError:
                    self._send_to(session, {"t": "status", "text": f"Invalid port in '{host_arg}'", "style": "bold red"})
                    return
            else:
                host, port = host_arg, DEFAULT_FEDERATION_PORT
            status = await self._federation.connect(host, port)
            self._send_to(session, {"t": "status", "text": status, "style": "bold cyan"})
        elif cmd == "/skills":
            index = self._skill_index()
            if not index:
                self._send_to(session, {"t": "status", "text": "No skills advertised", "style": "bold cyan"})
            else:
                lines = ["Advertised skills:"]
                for entry in index:
                    lines.append(f"  {entry['skill']} → {entry['agent_id']} ({entry['agent_type']})")
                self._send_to(session, {"t": "status", "text": "\n".join(lines), "style": "bold cyan"})
            # Also emit the structured event so programmatic CLI clients can consume it.
            self._send_to(session, {"t": "skills", "skills": index})
        else:
            self._send_to(
                session,
                {"t": "status", "text": f"Unsupported server command: {cmd}", "style": "bold yellow"},
            )

    def _artifact_summary(self, name: str, mime: str, data: bytes) -> str:
        if mime.startswith("application/json") or name.lower().endswith(".json"):
            try:
                return json.dumps(json.loads(data.decode("utf-8")), indent=2, default=str)
            except Exception:
                pass
        if mime.startswith("text/"):
            try:
                return data.decode("utf-8")
            except Exception:
                pass
        return f"[{name} — {mime or 'application/octet-stream'} — {len(data)} bytes]"

    async def _route_service_message(
        self,
        *,
        session: ClientSession,
        target: str,
        text: str,
        adapter,
        result_prefix: str,
    ) -> str:
        sender_id = session.agent_id
        now = datetime.now()
        rec = self._state.agents.get(target)
        if rec is not None:
            rec.fsm_state = "THINKING"
        self._broadcast({"t": "fsm", "agent_id": target, "fsm_state": "THINKING"})
        try:
            tool_name: str | None = None
            call_args: dict | None = None
            try:
                envelope = json.loads(text)
                if isinstance(envelope, dict) and "__tool__" in envelope:
                    tool_name = str(envelope["__tool__"])
                    call_args = dict(envelope.get("__args__") or {})
            except (json.JSONDecodeError, TypeError):
                pass
            if call_args is not None:
                if self._audit:
                    self._audit.log_msg("tool_call", **{
                        "from": sender_id, "to": target,
                        "tool": tool_name, "args": call_args,
                    })
                result = await adapter.call_structured(tool_name, call_args)
            else:
                if self._audit:
                    self._audit.log_msg("msg", **{"from": sender_id, "to": target, "text": text})
                result = await adapter.call(text, tool_name=tool_name)
            if self._audit:
                self._audit.log_msg("tool_result", **{
                    "from": target, "to": sender_id,
                    "tool": tool_name, "content": result,
                })
        except Exception as exc:
            result = f"({result_prefix} error: {exc})"
        finally:
            if rec is not None:
                rec.fsm_state = "IDLE"
            self._broadcast({"t": "fsm", "agent_id": target, "fsm_state": "IDLE"})
        if session.role == "human":
            self._send_to(session, {
                "t": "chat",
                "agent_id": target,
                "sender": target,
                "content": result,
                "direction": "in",
                "ts": now.isoformat(),
            })
            rec = self._state.agents.get(target)
            if rec is not None:
                rec.chat.append(ChatMessage(ts=now, sender=target, content=result, direction="in"))
        else:
            session.writer.write(
                encode_frame({"t": "msg", "from": target, "text": result})
            )
        self._record_feed(sender_id, target, text[:80])
        return result

    async def _route_message(self, session: ClientSession, target: str, text: str) -> None:
        sender_id = session.agent_id
        now = datetime.now()

        # ── Direct 1:1 message ────────────────────────────────────────────────
        if session.role == "human":
            rec = self._state.agents.get(target)
            if rec is not None and rec.agent_type not in _CHAT_TARGET_TYPES:
                self._send_to(
                    session,
                    {"t": "status", "text": f"'{target}' is a service agent, not a chat target", "style": "bold yellow"},
                )
                return

        if target in self._builtin_adapters:
            await self._route_service_message(
                session=session,
                target=target,
                text=text,
                adapter=self._builtin_adapters[target],
                result_prefix="builtin",
            )
            return

        # MCP service agents are not TCP sessions — route via MCPAdapter
        if target in self._mcp_adapters:
            mcp = self._mcp_adapters[target]
            result = await self._route_service_message(
                session=session,
                target=target,
                text=text,
                adapter=mcp,
                result_prefix="MCP",
            )
            # A service agent may embed a server command in its result using the
            # {"_mars_cmd": {"cmd": "spawn", "args": {...}}, "reply": "…"} pattern.
            # This lets MCP stdio subprocesses trigger server-side actions (e.g.
            # spawning a new agent) without needing a direct TCP connection.
            #
            # Supported cmds:
            #   spawn          — spawn a new LLM agent (provider/model)
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "_mars_cmd" in parsed:
                    srv_cmd = parsed["_mars_cmd"]
                    result = str(parsed.get("reply", "Done."))
                    cmd_name = srv_cmd.get("cmd", "")
                    if cmd_name == "spawn":
                        args = srv_cmd.get("args", {})
                        system_prompt = args.get("system_prompt")
                        kickoff = args.get("kickoff")
                        agent_name = args.get("name")
                        provider_raw = str(args.get("provider", ""))
                        model_raw = args.get("model") or ""
                        thinking = bool(args.get("thinking", False))
                        cache_prompts = args.get("cache_prompts")
                        max_tokens = args.get("max_tokens")
                        allowed_skills = args.get("allowed_skills") or args.get("skills")

                        extended = bool(
                            system_prompt or kickoff or agent_name or thinking
                            or cache_prompts is not None or max_tokens or allowed_skills
                        )
                        if extended:
                            # Extended spawn: build full llm_wire_agent command
                            if provider_raw:
                                cmd = self._build_wire_agent_cmd(
                                    self._server_addr,
                                    provider=provider_raw,
                                    model=str(model_raw) or None,
                                    name=agent_name,
                                    system_prompt=system_prompt,
                                    kickoff=kickoff,
                                    thinking=thinking,
                                    cache_prompts=cache_prompts,
                                    max_tokens=max_tokens,
                                    skills=allowed_skills,
                                )
                                self._spawn_subprocess(cmd)
                        else:
                            tokens = [provider_raw]
                            if model_raw:
                                tokens.append(str(model_raw))
                            if tokens[0]:
                                await self._spawn_from_tokens(tokens)
            except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
                pass

            return

        target_session = self._sessions_by_id.get(target)
        if target_session is None:
            self._send_to(session, {"t": "status", "text": f"Unknown target: {target}", "style": "bold red"})
            return

        # Track last_sender for any sender → agent routing so that service-agent
        # artifacts and replies always go back to whoever last messaged them
        # (human OR another agent acting as an LLM tool-caller).
        if target_session.role == "agent":
            target_session.last_sender = sender_id
        if session.role == "human":
            session.current_agent = target

        if self._audit:
            self._audit.log_msg("msg", **{"from": sender_id, "to": target, "text": text})

        if target_session.role == "human":
            self._send_to(target_session, {
                "t": "chat",
                "agent_id": sender_id,
                "sender": sender_id,
                "content": text,
                "direction": "in",
                "ts": now.isoformat(),
            })
            rec = self._state.agents.get(sender_id)
            if rec is not None:
                rec.chat.append(ChatMessage(ts=now, sender=sender_id, content=text, direction="in"))
        else:
            target_session.writer.write(
                encode_frame({"t": "msg", "from": sender_id, "text": text})
            )
            rec = self._state.agents.get(target)
            if rec is not None and session.role == "human":
                rec.chat.append(ChatMessage(ts=now, sender=sender_id, content=text, direction="out"))

        self._record_feed(sender_id, target, text[:80])

    def _deliver_artifact_to_human(
        self,
        sender_id: str,
        human_session: ClientSession,
        name: str,
        mime: str,
        data: bytes,
        raw_b64: str,
        now: datetime,
    ) -> None:
        """Send chat + artifact events to a single human session and update the
        sender's AgentRecord.  Extracted so both direct and room paths share it."""
        summary = self._artifact_summary(name, mime, data)
        chat_content = f"{name}\n{summary}" if summary != name else summary

        self._send_to(human_session, {
            "t": "chat",
            "agent_id": sender_id,
            "sender": sender_id,
            "content": chat_content,
            "direction": "in",
            "ts": now.isoformat(),
        })
        artifact_event: dict[str, Any] = {
            "t": "artifact",
            "agent_id": sender_id,
            "created_by": sender_id,
            "name": name,
            "mime": mime,
            "size": len(data),
        }
        if mime.startswith("image/") and len(data) <= 256 * 1024:
            artifact_event["preview_data"] = raw_b64
            artifact_event["preview_mime"] = mime
        self._send_to(human_session, artifact_event)

        rec = self._state.agents.get(sender_id)
        if rec is not None:
            rec.chat.append(ChatMessage(ts=now, sender=sender_id, content=chat_content, direction="in"))

    async def _handle_artifact(self, session: ClientSession, msg: dict[str, Any]) -> None:
        raw = msg.get("data")
        if not isinstance(raw, str):
            return
        try:
            data = base64.b64decode(raw)
        except Exception:
            self._send_to(session, {"t": "status", "text": "Invalid artifact base64", "style": "bold red"})
            return

        target_id = session.last_sender
        if not target_id:
            self._send_to(session, {"t": "status", "text": "No recipient for artifact", "style": "bold yellow"})
            return

        sender_id = session.agent_id
        name = str(msg.get("name") or "artifact.bin")
        mime = str(msg.get("mime") or "application/octet-stream")
        now = datetime.now()

        # ── Direct delivery ────────────────────────────────────────────────────
        target_session = self._sessions_by_id.get(target_id)
        if target_session is None:
            return

        if target_session.role != "human":
            # Deliver to an LLM tool-caller as a plain msg (structured result).
            summary = self._artifact_summary(name, mime, data)
            target_session.writer.write(
                encode_frame({"t": "msg", "from": sender_id, "text": summary})
            )
        else:
            self._deliver_artifact_to_human(sender_id, target_session, name, mime, data, raw, now)

        self._record_feed(sender_id, target_id, name[:80], event_type="reply")

    async def route_external_message(self, sender_id: str, target: str, text: str) -> None:
        """Route a message from a federated node directly to the target session."""
        now = datetime.now()

        target_session = self._sessions_by_id.get(target)
        if target_session is None:
            return
        if target_session.role == "human":
            self._send_to(target_session, {
                "t": "chat",
                "agent_id": sender_id,
                "sender": sender_id,
                "content": text,
                "direction": "in",
                "ts": now.isoformat(),
            })
        else:
            target_session.writer.write(
                encode_frame({"t": "msg", "from": sender_id, "text": text})
            )

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        addr = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) and len(peer) >= 2 else str(peer or "unknown")
        session = ClientSession(reader=reader, writer=writer, addr=addr)

        try:
            registered = False
            while not reader.at_eof():
                try:
                    raw = await reader.readline()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    break
                if not raw:
                    break
                msg = decode_frame(raw)
                if msg is None:
                    self._send_to(session, {"t": "status", "text": "Invalid JSON", "style": "bold red"})
                    continue
                if not registered:
                    if msg.get("t") != "hello":
                        self._send_to(session, {"t": "status", "text": "Expected hello", "style": "bold red"})
                        continue
                    session.name = str(msg.get("name") or session.name)
                    session.role = str(msg.get("role") or session.role)
                    session.current_agent = msg.get("current_agent") or session.current_agent
                    session.skills = [str(skill) for skill in msg.get("skills", [])]
                    session.agent_type = str(msg.get("agent_type")) if msg.get("agent_type") else None
                    session.model = str(msg.get("model") or "")
                    session.vendor = str(msg.get("vendor") or "")
                    await self._register_session(session)
                    registered = True
                    continue

                mtype = msg.get("t")
                if mtype == "msg":
                    target = str(msg.get("target") or session.current_agent or "")
                    text = str(msg.get("text") or "")
                    if not target:
                        self._send_to(session, {"t": "status", "text": "No target agent selected", "style": "bold red"})
                        continue
                    await self._route_message(session, target, text)
                elif mtype == "fsm":
                    # Agent reports its own FSM state change (e.g. THINKING → IDLE).
                    # Update the AgentRecord and broadcast to all connected clients.
                    aid = session.agent_id
                    if aid:
                        rec = self._state.agents.get(aid)
                        if rec is not None:
                            rec.fsm_state    = str(msg.get("fsm_state")    or rec.fsm_state)
                            rec.fsm_strategy = str(msg.get("fsm_strategy") or rec.fsm_strategy)
                            rec.fsm_loop     = msg.get("fsm_loop")
                        self._broadcast({
                            "t":            "fsm",
                            "agent_id":     aid,
                            "fsm_state":    msg.get("fsm_state",    "—"),
                            "fsm_strategy": msg.get("fsm_strategy", "—"),
                            "fsm_loop":     msg.get("fsm_loop"),
                        })
                elif mtype == "artifact":
                    await self._handle_artifact(session, msg)
                elif mtype == "cmd":
                    structured = msg.get("cmd")
                    if structured:
                        await self._handle_structured_command(session, str(structured), msg)
                    else:
                        await self._handle_command(session, str(msg.get("text") or ""))
        finally:
            await self._remove_session(session)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def serve(
        self,
        host: str,
        port: int,
        ready_future: asyncio.Future[None] | None = None,
    ) -> None:
        self._server_host = host
        self._server_port = port
        # Use the literal bind address for loopback (tests); use the outbound
        # LAN IP when binding on all interfaces so remote agents can connect.
        if host in ("0.0.0.0", "::", ""):
            self._server_addr = f"{_local_ip()}:{port}"
        else:
            self._server_addr = f"{host}:{port}"
        await self.start_builtin_services()
        try:
            server = await asyncio.start_server(
                self.handle_client,
                host,
                port,
                limit=16 * 1024 * 1024,
            )
        except Exception as exc:
            if ready_future is not None and not ready_future.done():
                ready_future.set_exception(exc)
            raise
        print(f"TCP server listening on {host}:{port}", flush=True)
        if ready_future is not None and not ready_future.done():
            ready_future.set_result(None)
        async with server:
            await server.serve_forever()
