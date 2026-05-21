from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mars.client.cli.models import AgentRecord, ChatMessage, FeedItem, MARSState, DEFAULT_PORT, DEFAULT_FEDERATION_PORT
from mars.client.cli.service_manager import _auto_spawn_free_agents, _launch_service_agent
from mars.client.cli.utils import _load_dotenv, _local_ip, _normalize_agent_type
from mars.constants import DEFAULT_HTTP_PORT, DEFAULT_WS_PORT
from mars.storage.scopes.store import ScopeStore
from mars.runtime.services.registry import get as get_agent_spec, resolve_command
from mars.runtime.server.mcp_adapter import MCPAdapter

logger = logging.getLogger(__name__)

# Project root — four levels up from mars/runtime/server/main.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_GROUP_ROOM = "group"


def _agent_payload(rec: AgentRecord, state: MARSState) -> dict[str, Any]:
    """Build the canonical agent payload dict shared by TCP state-dump and REST API."""
    return {
        "agent_id": rec.agent_id,
        "agent_type": rec.agent_type,
        "domain": rec.domain,
        "platform": rec.platform,
        "server_addr": rec.server_addr,
        "is_current": rec.is_current,
        "status": rec.status,
        "fsm_state": rec.fsm_state,
        "fsm_strategy": rec.fsm_strategy,
        "fsm_loop": rec.fsm_loop,
        "has_reply": rec.has_reply,
        "pending_reply": rec.pending_reply,
        "verbose": rec.verbose,
        "avatar": rec.avatar,
        "model": rec.model,
        "vendor": rec.vendor,
        "competence_level": rec.competence_level,
        "competence_score": rec.competence_score,
        "skills": list(rec.skills),
        "tool_schemas": list(rec.tool_schemas),
        "role": state.agent_roles.get(rec.agent_id, ""),
        "behaviour": state.agent_behaviours.get(rec.agent_id, ""),
    }


def _scope_payload(scope: Any) -> dict[str, Any]:
    """Build the canonical scope payload dict."""
    return {
        "id": scope.id,
        "title": scope.title,
        "path": scope.path,
        "parent_id": scope.parent_id,
        "required_skills": list(getattr(scope, "required_skills", [])),
    }


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
        self._clients: list[ClientSession] = []
        self._sessions_by_id: dict[str, ClientSession] = {}
        self._rooms: dict[str, set[str]] = {}  # room_name → set[agent_id]
        self._mcp_adapters: dict[str, MCPAdapter] = {}  # agent_id → MCPAdapter
        self._server_addr: str = ""
        self._server_host: str = "127.0.0.1"
        self._server_port: int = DEFAULT_PORT
        self._spawned_pids: list[int] = []
        self._state._event_listeners.append(self._broadcast)

    @staticmethod
    def _unique_agent_id(requested: str, active: set[str]) -> str:
        import re as _re
        match = _re.match(r"^(.+?)@(\d+)$", requested)
        base = match.group(1) if match else requested
        counter = 1
        candidate = f"{base}@{counter}"
        while candidate in active:
            counter += 1
            candidate = f"{base}@{counter}"
        return candidate

    def _spawn_subprocess(self, cmd: list[str]) -> None:
        import pathlib
        log_dir = pathlib.Path("artifacts") / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        # Use the --provider value (or last arg) as log file label
        label = next(
            (cmd[i + 1] for i, a in enumerate(cmd) if a == "--provider" and i + 1 < len(cmd)),
            cmd[-1].replace("-", "_"),
        )
        log_file = open(log_dir / f"wire_{label}.log", "a")  # noqa: SIM115
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        self._spawned_pids.append(proc.pid)

    async def start_mcp_agents(self) -> None:
        """Start all free MCP-protocol service agents as stdio subprocesses."""
        from mars.runtime.services.registry import all_specs
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
            try:
                await adapter.stop()
            except Exception:
                pass
            self._state.agents.pop(agent_id, None)
        self._mcp_adapters.clear()

    def _room_join(self, room_name: str, agent_id: str) -> None:
        """Add agent_id to room, broadcast updated member list to all members."""
        if room_name not in self._rooms:
            self._rooms[room_name] = set()
        self._rooms[room_name].add(agent_id)
        ev = {"t": "room_join", "room": room_name, "members": sorted(self._rooms[room_name])}
        for mid in list(self._rooms[room_name]):
            s = self._sessions_by_id.get(mid)
            if s:
                self._send_to(s, ev)

    def _room_part(self, room_name: str, agent_id: str) -> None:
        """Remove agent_id from room, notify remaining members and the leaver."""
        members = self._rooms.get(room_name)
        if not members or agent_id not in members:
            return
        members.discard(agent_id)
        ev = {"t": "room_part", "room": room_name, "member": agent_id}
        for mid in list(members) + [agent_id]:
            s = self._sessions_by_id.get(mid)
            if s:
                self._send_to(s, ev)
        if not members:
            self._rooms.pop(room_name, None)

    def _state_dump(self) -> dict[str, Any]:
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
        }

    def _send_to(self, session: ClientSession, ev: dict[str, Any]) -> None:
        try:
            if session.writer.is_closing():
                raise ConnectionError("client closed")
            session.writer.write((json.dumps(ev, default=str) + "\n").encode("utf-8"))
        except Exception:
            try:
                session.writer.close()
            except Exception:
                pass

    def _broadcast(self, ev: dict[str, Any]) -> None:
        payload = (json.dumps(ev, default=str) + "\n").encode("utf-8")
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
            try:
                session.writer.close()
            except Exception:
                pass

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
            agent_type = _normalize_agent_type(session.agent_type or "ServiceAgent")
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

        # Auto-create a room for LLM agents and join with all connected humans.
        if agent_type == "LLMAgent":
            room_name = agent_id
            self._room_join(room_name, agent_id)
            for other in list(self._clients):
                if other.role == "human" and other.agent_id and other is not session:
                    self._room_join(room_name, other.agent_id)
                    self._send_to(other, {"t": "switch", "current_agent": f"#{room_name}"})

            llm_ids = [
                c.agent_id for c in self._clients
                if c.agent_id
                and self._state.agents.get(c.agent_id) is not None
                and self._state.agents[c.agent_id].agent_type == "LLMAgent"
            ]
            if len(llm_ids) >= 2:
                for llm_id in llm_ids:
                    self._room_join(_GROUP_ROOM, llm_id)
                for other in list(self._clients):
                    if other.role == "human" and other.agent_id:
                        self._room_join(_GROUP_ROOM, other.agent_id)
                        self._send_to(other, {"t": "switch", "current_agent": f"#{_GROUP_ROOM}"})

        elif session.role == "human":
            if _GROUP_ROOM in self._rooms:
                self._room_join(_GROUP_ROOM, agent_id)
                self._send_to(session, {"t": "switch", "current_agent": f"#{_GROUP_ROOM}"})

    async def _remove_session(self, session: ClientSession) -> None:
        # Leave all rooms before removing the session so room_part events can be delivered.
        if session.agent_id:
            for room_name in list(self._rooms.keys()):
                if session.agent_id in self._rooms.get(room_name, set()):
                    self._room_part(room_name, session.agent_id)

        if _GROUP_ROOM in self._rooms:
            llm_in_group = [
                mid for mid in self._rooms.get(_GROUP_ROOM, set())
                if mid in self._state.agents
                and self._state.agents[mid].agent_type == "LLMAgent"
            ]
            if len(llm_in_group) < 2:
                for mid in list(self._rooms.get(_GROUP_ROOM, set())):
                    self._room_part(_GROUP_ROOM, mid)
        if session in self._clients:
            self._clients.remove(session)
        if session.agent_id and self._sessions_by_id.get(session.agent_id) is session:
            self._sessions_by_id.pop(session.agent_id, None)
        if session.agent_id and session.agent_id in self._state.agents:
            self._state.agents.pop(session.agent_id, None)
            self._state.agent_roles.pop(session.agent_id, None)
            self._state.agent_behaviours.pop(session.agent_id, None)
            self._state._fire({"t": "despawn", "agent_id": session.agent_id})

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
                agent_type="ServiceAgent",
                skills=skills,
                tool_schemas=tool_schemas,
            )
            self._state.agents[agent_id] = rec
            self._state._fire({
                "t": "spawn",
                "agent_id": agent_id,
                "name": spec.name,
                "agent_type": "ServiceAgent",
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

    async def _spawn_from_tokens(self, tokens: list[str]) -> str:
        if not tokens:
            return "Usage: /spawn <provider|service> [args]"

        spec = get_agent_spec(tokens[0])
        if spec is not None:
            if spec.protocol == "mcp":
                return await self._spawn_mcp_agent(spec)
            pid, _workdir = _launch_service_agent(spec, self._server_addr, tokens[1:])
            self._spawned_pids.append(pid)
            return f"Spawned service '{spec.name}' (pid {pid})"

        provider_name = tokens[0]
        model: str | None = None
        agent_name: str | None = None
        api_key: str | None = None
        host: str | None = None
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
            elif token.startswith("--"):
                index += 1
            else:
                model = token
                index += 1

        cmd = [
            sys.executable,
            "-m",
            "mars.runtime.services.llm_wire_agent",
            "--server",
            self._server_addr,
            "--provider",
            provider_name,
        ]
        if model:
            cmd += ["--model", model]
        if api_key:
            cmd += ["--key", api_key]
        if host:
            cmd += ["--host", host]
        if agent_name:
            cmd += ["--name", agent_name]
        self._spawn_subprocess(cmd)
        return f"Spawned LLM provider '{provider_name}'" + (f" [{model}]" if model else "")

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
                try:
                    target_session.writer.close()
                except Exception:
                    pass
                self._send_to(session, {"t": "status", "text": f"Stopped '{target_id}'", "style": "bold cyan"})
            elif target_id in self._mcp_adapters:
                adapter = self._mcp_adapters.pop(target_id)
                try:
                    await adapter.stop()
                except Exception:
                    pass
                if target_id in self._state.agents:
                    self._state.agents.pop(target_id, None)
                    self._state._fire({"t": "despawn", "agent_id": target_id})
                self._send_to(session, {"t": "status", "text": f"Stopped MCP agent '{target_id}'", "style": "bold cyan"})
            else:
                self._send_to(session, {"t": "status", "text": f"Agent '{target_id}' not found", "style": "bold yellow"})
        elif cmd == "/switch":
            session.current_agent = args[0] if args else None
            self._send_to(session, {"t": "switch", "current_agent": session.current_agent})
        elif cmd == "/join":
            if not args:
                self._send_to(session, {"t": "status", "text": "Usage: /join <room> [agents…]", "style": "bold yellow"})
                return
            room_name = args[0].lstrip("#")
            self._room_join(room_name, session.agent_id)
            for extra in args[1:]:
                if extra in self._sessions_by_id:
                    self._room_join(room_name, extra)
                else:
                    self._send_to(session, {"t": "status", "text": f"Agent '{extra}' not connected", "style": "bold yellow"})
            self._send_to(session, {"t": "switch", "current_agent": f"#{room_name}"})
        elif cmd == "/part":
            room_name = args[0].lstrip("#") if args else None
            if not room_name:
                # Leave the first room the session is currently a member of
                for rn, members in self._rooms.items():
                    if session.agent_id in members:
                        room_name = rn
                        break
            if room_name:
                self._room_part(room_name, session.agent_id)
            else:
                self._send_to(session, {"t": "status", "text": "Not in any room", "style": "bold yellow"})
        elif cmd == "/list":
            if not self._rooms:
                self._send_to(session, {"t": "status", "text": "No active rooms", "style": "bold cyan"})
            else:
                lines = ["Active rooms:"]
                for rn, members in sorted(self._rooms.items()):
                    lines.append(f"  #{rn}: {', '.join(sorted(members))}")
                self._send_to(session, {"t": "status", "text": "\n".join(lines), "style": "bold cyan"})
        else:
            self._send_to(session, {"t": "status", "text": f"Unsupported server command: {cmd}", "style": "bold yellow"})

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

    async def _route_message(self, session: ClientSession, target: str, text: str) -> None:
        sender_id = session.agent_id
        now = datetime.now()

        # ── Room broadcast ────────────────────────────────────────────────────
        if target.startswith("#"):
            room_name = target[1:]
            members = self._rooms.get(room_name)
            if not members:
                self._send_to(session, {"t": "status", "text": f"Room #{room_name} not found", "style": "bold red"})
                return
            for mid in list(members):
                if mid == sender_id:
                    continue  # client already shows its own message optimistically
                member_session = self._sessions_by_id.get(mid)
                if member_session is None:
                    continue
                if member_session.role == "human":
                    self._send_to(member_session, {
                        "t": "room_msg",
                        "room": room_name,
                        "sender": sender_id,
                        "content": text,
                        "ts": now.isoformat(),
                    })
                else:
                    # Deliver to LLM/agent as msg; include room context in "from"
                    member_session.writer.write(
                        (json.dumps({"t": "msg", "from": f"#{room_name}", "sender": sender_id, "text": text}) + "\n").encode("utf-8")
                    )
                    member_session.last_sender = f"#{room_name}"
            self._record_feed(sender_id, target, text[:80])
            return

        # ── Direct 1:1 message ────────────────────────────────────────────────
        # MCP service agents are not TCP sessions — route via MCPAdapter
        if target in self._mcp_adapters:
            mcp = self._mcp_adapters[target]
            # Broadcast THINKING so clients show the blue spinner
            rec = self._state.agents.get(target)
            if rec is not None:
                rec.fsm_state = "THINKING"
            self._broadcast({"t": "fsm", "agent_id": target, "fsm_state": "THINKING"})
            try:
                # Wire agents may send a JSON envelope for structured tool calls:
                # {"__tool__": "tool_name", "__args__": {...}}
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
                    result = await mcp.call_structured(tool_name, call_args)
                else:
                    result = await mcp.call(text, tool_name=tool_name)
            except Exception as exc:
                result = f"(MCP error: {exc})"
            finally:
                # Always restore IDLE so the dot goes green
                if rec is not None:
                    rec.fsm_state = "IDLE"
                self._broadcast({"t": "fsm", "agent_id": target, "fsm_state": "IDLE"})
            # A service agent may embed a server command in its result using the
            # {"_mars_cmd": {"cmd": "spawn", "args": {...}}, "reply": "…"} pattern.
            # This lets MCP stdio subprocesses trigger server-side actions (e.g.
            # spawning a new agent) without needing a direct TCP connection.
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "_mars_cmd" in parsed:
                    srv_cmd = parsed["_mars_cmd"]
                    result = str(parsed.get("reply", "Done."))
                    cmd_name = srv_cmd.get("cmd", "")
                    if cmd_name == "spawn":
                        args = srv_cmd.get("args", {})
                        tokens = [str(args.get("provider", ""))]
                        if args.get("model"):
                            tokens.append(str(args["model"]))
                        if tokens[0]:
                            await self._spawn_from_tokens(tokens)
            except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
                pass

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
                    (json.dumps({"t": "msg", "from": target, "text": result}) + "\n").encode("utf-8")
                )
            self._record_feed(sender_id, target, text[:80])
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
            target_session.writer.write((json.dumps({"t": "msg", "from": sender_id, "text": text}) + "\n").encode("utf-8"))
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

        # ── Room broadcast ─────────────────────────────────────────────────────
        if target_id.startswith("#"):
            room_name = target_id[1:]
            members = self._rooms.get(room_name, set())
            summary = self._artifact_summary(name, mime, data)
            for mid in list(members):
                if mid == sender_id:
                    continue
                member_session = self._sessions_by_id.get(mid)
                if member_session is None:
                    continue
                if member_session.role == "human":
                    self._deliver_artifact_to_human(sender_id, member_session, name, mime, data, raw, now)
                else:
                    member_session.writer.write(
                        (json.dumps({"t": "msg", "from": sender_id, "text": summary}) + "\n").encode("utf-8")
                    )
            self._record_feed(sender_id, target_id, name[:80], event_type="reply")
            return

        # ── Direct delivery ────────────────────────────────────────────────────
        target_session = self._sessions_by_id.get(target_id)
        if target_session is None:
            return

        if target_session.role != "human":
            # Deliver to an LLM tool-caller as a plain msg (structured result).
            summary = self._artifact_summary(name, mime, data)
            target_session.writer.write(
                (json.dumps({"t": "msg", "from": sender_id, "text": summary}) + "\n").encode("utf-8")
            )
        else:
            self._deliver_artifact_to_human(sender_id, target_session, name, mime, data, raw, now)

        self._record_feed(sender_id, target_id, name[:80], event_type="reply")

    async def route_external_message(self, sender_id: str, target: str, text: str) -> None:
        """Route a message from a federated node.  Supports both direct and room targets."""
        now = datetime.now()

        if target.startswith("#"):
            room_name = target[1:]
            for mid in list(self._rooms.get(room_name, set())):
                if mid == sender_id:
                    continue
                member_session = self._sessions_by_id.get(mid)
                if member_session is None:
                    continue
                if member_session.role == "human":
                    self._send_to(member_session, {
                        "t": "room_msg",
                        "room": room_name,
                        "sender": sender_id,
                        "content": text,
                        "ts": now.isoformat(),
                    })
                else:
                    member_session.writer.write(
                        (json.dumps({"t": "msg", "from": f"#{room_name}", "sender": sender_id, "text": text}) + "\n").encode("utf-8")
                    )
            return

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
            target_session.writer.write((json.dumps({"t": "msg", "from": sender_id, "text": text}) + "\n").encode("utf-8"))

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
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except Exception:
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


class MARSRestAPI:
    def __init__(self, server: MARSServer, state: MARSState, cors_allow: list[str] | None = None) -> None:
        self._server = server
        self._state = state
        self._cors_allow = list(cors_allow or [])

    async def _route(self, method: str, path: str, body: bytes) -> tuple[str, Any]:
        clean_path = path.split("?", 1)[0]
        if method == "OPTIONS":
            return "200 OK", {}
        if method == "GET" and clean_path == "/":
            return "200 OK", {
                "service": "MARS REST API",
                "endpoints": ["GET /", "GET /agents", "POST /spawn", "POST /message", "GET /scopes"],
            }
        if method == "GET" and clean_path == "/agents":
            return "200 OK", [_agent_payload(rec, self._state) for rec in self._state.agents.values()]
        if method == "GET" and clean_path == "/scopes":
            return "200 OK", [_scope_payload(scope) for scope in self._state.scopes]
        if method == "GET" and clean_path == "/problems":
            return "200 OK", []
        if method == "POST" and clean_path == "/spawn":
            payload = json.loads(body.decode("utf-8") or "{}")
            provider = payload.get("provider")
            if not provider:
                return "400 Bad Request", {"ok": False, "error": "provider required"}
            args = [str(provider)]
            if payload.get("model"):
                args.append(str(payload["model"]))
            if payload.get("name"):
                args += ["--name", str(payload["name"])]
            if payload.get("key"):
                args += ["--key", str(payload["key"])]
            if payload.get("host"):
                args += ["--host", str(payload["host"])]
            status = await self._server._spawn_from_tokens(args)
            return "200 OK", {"ok": True, "status": status}
        if method == "POST" and clean_path == "/message":
            payload = json.loads(body.decode("utf-8") or "{}")
            target = payload.get("to")
            text = payload.get("text")
            if not target or text is None:
                return "400 Bad Request", {"ok": False, "error": "to and text required"}
            await self._server.route_external_message("rest-api", str(target), str(text))
            return "200 OK", {"ok": True}
        return "404 Not Found", {"ok": False, "error": "not found"}

    async def handle_http(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status = "500 Internal Server Error"
        payload: Any = {"ok": False, "error": "internal error"}
        headers: dict[str, str] = {}
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            header_block, _, body = head.partition(b"\r\n\r\n")
            lines = header_block.decode("utf-8", errors="ignore").split("\r\n")
            request_line = lines[0]
            parts = request_line.split()
            if len(parts) < 2:
                raise ValueError("invalid request")
            method, path = parts[0], parts[1]
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            content_length = int(headers.get("content-length", "0") or "0")
            if content_length > len(body):
                body += await reader.readexactly(content_length - len(body))
            status, payload = await self._route(method, path, body)
        except asyncio.IncompleteReadError:
            status, payload = "400 Bad Request", {"ok": False, "error": "incomplete request"}
        except json.JSONDecodeError:
            status, payload = "400 Bad Request", {"ok": False, "error": "invalid json"}
        except Exception as exc:
            status, payload = "400 Bad Request", {"ok": False, "error": str(exc)}
        body_bytes = json.dumps(payload, default=str).encode("utf-8")
        cors_headers = ""
        if self._cors_allow:
            origin_header = headers.get("origin", "")
            if "*" in self._cors_allow:
                allow_origin = "*"
            elif origin_header and origin_header in self._cors_allow:
                allow_origin = origin_header
            else:
                allow_origin = ""
            if allow_origin:
                cors_headers = (
                    f"Access-Control-Allow-Origin: {allow_origin}\r\n"
                    "Access-Control-Allow-Headers: Content-Type\r\n"
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                )
                if allow_origin != "*":
                    cors_headers += "Vary: Origin\r\n"
        response = (
            f"HTTP/1.1 {status}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"{cors_headers}"
            "Connection: close\r\n\r\n"
        ).encode("utf-8") + body_bytes
        writer.write(response)
        try:
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def serve(self, host: str, port: int = DEFAULT_HTTP_PORT) -> None:
        server = await asyncio.start_server(self.handle_http, host, port)
        async with server:
            await server.serve_forever()


class MARSWebSocketServer:
    def __init__(self, server: MARSServer, state: MARSState) -> None:
        self._server = server
        self._state = state
        self._clients_ws: list[asyncio.StreamWriter] = []
        self._state._event_listeners.append(self._broadcast_ws)

    def _state_dump(self) -> dict[str, Any]:
        return self._server._state_dump()

    def _send_ws_text(self, writer: asyncio.StreamWriter, text: str) -> None:
        payload = text.encode("utf-8")
        frame = bytearray([0x81])
        length = len(payload)
        if length < 126:
            frame.append(length)
        elif length < (1 << 16):
            frame.append(126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(127)
            frame.extend(length.to_bytes(8, "big"))
        writer.write(bytes(frame) + payload)

    def _broadcast_ws(self, ev: dict[str, Any]) -> None:
        data = json.dumps(ev, default=str)
        dead: list[asyncio.StreamWriter] = []
        for writer in list(self._clients_ws):
            try:
                if writer.is_closing():
                    raise ConnectionError("client closed")
                self._send_ws_text(writer, data)
            except Exception:
                dead.append(writer)
        for writer in dead:
            if writer in self._clients_ws:
                self._clients_ws.remove(writer)
            try:
                writer.close()
            except Exception:
                pass

    _WS_MAX_PAYLOAD = 4 * 1024 * 1024

    async def _read_ws_frame(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str | None:
        first, second = await reader.readexactly(2)
        opcode = first & 0x0F
        masked = (second & 0x80) != 0
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(await reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await reader.readexactly(8), "big")
        if length > self._WS_MAX_PAYLOAD:
            writer.write(b"\x88\x02\x03\xF0")
            try:
                await writer.drain()
            except Exception:
                pass
            return None
        mask = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 8:
            return None
        if opcode == 9:
            writer.write(b"\x8A\x00")
            return ""
        if opcode != 1:
            return ""
        return payload.decode("utf-8", errors="ignore")

    async def handle_ws_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
            lines = raw.decode("utf-8", errors="ignore").split("\r\n")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            key = headers.get("sec-websocket-key")
            if not key:
                raise ValueError("missing websocket key")
            accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("utf-8")).digest()).decode("ascii")
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            )
            writer.write(response.encode("utf-8"))
            await writer.drain()
            self._clients_ws.append(writer)
            self._send_ws_text(writer, json.dumps(self._state_dump(), default=str))
            current_agent: str | None = None
            while True:
                data = await self._read_ws_frame(reader, writer)
                if data is None:
                    break
                if not data:
                    continue
                try:
                    msg = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get("t")
                if mtype == "hello":
                    current_agent = msg.get("current_agent") or current_agent
                elif mtype == "cmd":
                    text = str(msg.get("text") or "")
                    if text.startswith("/switch"):
                        parts = text.split(maxsplit=1)
                        current_agent = parts[1].strip() if len(parts) > 1 else None
                        self._send_ws_text(writer, json.dumps({"t": "switch", "current_agent": current_agent}))
                    else:
                        try:
                            status = await self._server._spawn_from_tokens(shlex.split(text)[1:]) if text.startswith("/spawn") else f"Unsupported server command: {text}"
                        except Exception as exc:
                            status = str(exc)
                        self._send_ws_text(writer, json.dumps({"t": "status", "text": status, "style": "bold cyan"}))
                elif mtype == "msg":
                    text = str(msg.get("text") or "")
                    target = str(msg.get("target") or current_agent or "")
                    if not target:
                        self._send_ws_text(writer, json.dumps({"t": "status", "text": "No target agent selected", "style": "bold red"}))
                        continue
                    await self._server.route_external_message("ws-client", target, text)
        finally:
            if writer in self._clients_ws:
                self._clients_ws.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def serve(self, host: str, port: int = DEFAULT_WS_PORT) -> None:
        server = await asyncio.start_server(self.handle_ws_client, host, port)
        async with server:
            await server.serve_forever()


class MARSAuditLog:
    def __init__(self, path: str = "mars_audit.jsonl") -> None:
        self._path = path
        self._fh = open(path, "a", encoding="utf-8")
        try:
            import os
            import stat
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, NotImplementedError):
            pass

    def log(self, event: dict[str, Any]) -> None:
        payload = {"ts": datetime.now().isoformat(), **event}
        self._fh.write(json.dumps(payload, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.flush()
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self) -> "MARSAuditLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


async def _async_server(args: argparse.Namespace) -> None:
    def _suppress_connection_reset(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        loop.default_exception_handler(context)

    asyncio.get_running_loop().set_exception_handler(_suppress_connection_reset)

    state = MARSState(platform_name="mars-server")
    scope_store = ScopeStore(Path("scopes"))
    state.scopes = scope_store.load_all()

    audit = MARSAuditLog(getattr(args, "audit", "mars_audit.jsonl"))
    state._event_listeners.append(audit.log)

    mars_server = MARSServer(state)
    cors_raw = getattr(args, "cors_allow", None)
    cors_list = [origin.strip() for origin in cors_raw.split(",")] if cors_raw else []
    rest_api = MARSRestAPI(mars_server, state, cors_allow=cors_list)
    ws_server = MARSWebSocketServer(mars_server, state)

    tcp_ready = asyncio.get_running_loop().create_future()
    tcp_task = asyncio.create_task(mars_server.serve(args.host, args.port, ready_future=tcp_ready))
    rest_task = asyncio.create_task(rest_api.serve(args.host, args.http_port))
    ws_task = asyncio.create_task(ws_server.serve(args.host, args.ws_port))
    await tcp_ready

    server_host = "localhost" if args.host in ("0.0.0.0", "::") else args.host
    server_addr = f"{server_host}:{args.port}"
    _auto_spawn_free_agents(server_addr)
    await mars_server.start_mcp_agents()

    async def _ollama_reachable(host: str = "http://localhost:11434") -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{host.rstrip('/')}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    try:
        from mars.client.providers.copilot import _resolve_token as _copilot_token
    except ImportError:
        def _copilot_token(key=None):
            return None

    if args.provider:
        providers = list(args.provider)
    else:
        ollama_host = getattr(args, "ollama_host", None) or "http://localhost:11434"
        if await _ollama_reachable(ollama_host):
            providers = ["ollama"]
            print("🦙 Ollama detected — spawning Ollama LLM agent (use --provider to override)", flush=True)
        elif _copilot_token(getattr(args, "key", None)):
            providers = ["copilot"]
            print("🤖 Copilot token detected — spawning Copilot LLM agent", flush=True)
        else:
            providers = []

    for provider in providers:
        cmd = [
            sys.executable,
            "-m",
            "mars.runtime.services.llm_wire_agent",
            "--server",
            server_addr,
            "--provider",
            provider,
        ]
        if getattr(args, "key", None):
            cmd += ["--key", args.key]
        if provider == "ollama" and getattr(args, "ollama_host", None):
            cmd += ["--host", args.ollama_host]
        if getattr(args, "model", None) and len(providers) == 1:
            cmd += ["--model", args.model]
        mars_server._spawn_subprocess(cmd)

    print(f"🤖 MARS Server ready — {len(state.agents)} agents", flush=True)
    print(f"   TCP  :  {args.host}:{args.port}", flush=True)
    print(f"   REST :  http://{args.host}:{args.http_port}", flush=True)
    print(f"   WS   :  ws://{args.host}:{args.ws_port}", flush=True)
    print(f"   Audit:  {args.audit}", flush=True)

    try:
        await asyncio.gather(tcp_task, rest_task, ws_task)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await mars_server.stop_mcp_agents()
        audit.close()


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _load_dotenv()
    parser = argparse.ArgumentParser(prog="mars-server", description="MARS headless TCP router")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Interface to bind TCP / REST / WebSocket listeners on. Defaults to "
            "127.0.0.1 (loopback only) to keep an unauthenticated server off the "
            "network."
        ),
    )
    parser.add_argument(
        "--cors-allow",
        default=None,
        help="Comma-separated list of origins allowed by the REST API",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--federation-port", type=int, default=DEFAULT_FEDERATION_PORT, dest="federation_port")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, dest="http_port")
    parser.add_argument("--ws-port", type=int, default=DEFAULT_WS_PORT, dest="ws_port")
    parser.add_argument("--provider", nargs="+", default=None, help="LLM provider(s) to spawn on startup")
    parser.add_argument("--model", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--ollama-host", default=None, dest="ollama_host", help="Ollama server URL")
    parser.add_argument("--connect", nargs="*", default=None, metavar="HOST[:PORT]", help="Unused compatibility option")
    parser.add_argument("--audit", default="mars_audit.jsonl")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(_async_server(args))


if __name__ == "__main__":
    main()
