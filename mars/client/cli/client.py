from __future__ import annotations

import asyncio
import json
import sys
import threading
from collections import deque
from datetime import datetime
from typing import Any

from mars.client.cli.models import (
    MARSState, AgentRecord, ChatMessage, FeedItem,
    HUMAN_AVATARS, _is_conversational, _nav_sidebar, _nav_connections,
    _sync_sidebar_cursor, _nav_mcp,
)
from mars.client.cli.renderer import MARSRenderer
from mars.client.cli.utils import _normalize_agent_type, _normalize_echo_mode, _running_service_agent_names
from mars.client.cli.commands import (
    _expand_file_mentions,
    _handle_bang_cmd,
    _cmd_help,
    _cmd_agents,
    _cmd_agents_available,
    _cmd_read,
    _cmd_copy,
    _cmd_new,
    _cmd_context,
    _cmd_instructions,
    _cmd_compact,
    _cmd_share,
    _cmd_rewind,
    _cmd_search,
    _cmd_ask,
    _cmd_plan,
    _cmd_version,
    _cmd_theme,
)

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.table import Table
    _RICH = True
except ImportError:
    _RICH = False
    Console = None  # type: ignore[misc,assignment]

class MARSClientTerminal:
    """Legacy thin TUI client kept for compatibility with mars-server over TCP.

    Receives JSON-line events and applies them to a local MARSState copy.
    Forwards commands to the server; handles a small set of purely local commands.
    """

    # Commands handled entirely on the client (no server round-trip needed)
    _LOCAL = frozenset({
        "switch", "avatar", "verbose", "read", "agents", "status", "echo",
        "help", "quit",
        "new", "rewind", "context", "share", "search", "version", "theme",
        "copy", "compact", "instructions", "ask", "plan",
    })

    def __init__(
        self,
        reader: "asyncio.StreamReader",
        writer: "asyncio.StreamWriter",
        state: MARSState,
        server_addr: str = "",
    ) -> None:
        self._reader      = reader
        self._writer      = writer
        self._state       = state
        self._server_addr = server_addr
        self._renderer    = MARSRenderer(state)
        self._console     = Console(highlight=False) if _RICH else None
        self._input_lock  = threading.Lock()
        self._input_buffer: str = ""

    # ------------------------------------------------------------------
    # Event application (server → client)
    # ------------------------------------------------------------------

    def _apply_event(self, ev: dict) -> None:
        t = ev.get("t", "")

        if t == "state":
            self._state.platform_name = ev.get("platform_name", "mars")
            self._state.agent_roles.clear()
            self._state.agent_behaviours.clear()
            for aid, data in ev.get("agents", {}).items():
                self._state.agents[aid] = AgentRecord(
                    agent_id          = aid,
                    agent_type        = _normalize_agent_type(data.get("agent_type", "Agent")),
                    domain            = data.get("domain", "default"),
                    platform          = data.get("platform", "local"),
                    fsm_state         = data.get("fsm_state", "—"),
                    fsm_strategy      = data.get("fsm_strategy", "—"),
                    avatar            = data.get("avatar", ""),
                    model             = data.get("model", ""),
                    vendor            = data.get("vendor", ""),
                    competence_level  = data.get("competence_level", "COMPETENT"),
                    competence_score  = float(data.get("competence_score", 50.0)),
                    skills            = data.get("skills", []),
                    tool_schemas      = list(data.get("tool_schemas") or []),
                    server_addr       = data.get("server_addr", ""),
                )
                role = str(data.get("role") or "")
                behaviour = str(data.get("behaviour") or "")
                if role:
                    self._state.agent_roles[aid] = role
                else:
                    self._state.agent_roles.pop(aid, None)
                if behaviour:
                    self._state.agent_behaviours[aid] = behaviour
            # Restore feed (server sends newest-first; deque([newest,...]) keeps order)
            feed_items = []
            for fd in ev.get("feed", []):
                try:
                    ts = datetime.fromisoformat(fd["ts"])
                except Exception:
                    ts = datetime.now()
                feed_items.append(FeedItem(
                    ts=ts,
                    event_type=fd.get("event_type", "message"),
                    from_id=fd.get("from_id", ""),
                    to_id=fd.get("to_id", ""),
                    snippet=fd.get("snippet", ""),
                    performative=fd.get("performative", "INFORM"),
                ))
            self._state.feed = deque(feed_items, maxlen=30)
            # Restore per-agent chat history
            for aid, msgs in ev.get("chats", {}).items():
                rec = self._state.agents.get(aid)
                if rec:
                    for cm in msgs:
                        try:
                            ts = datetime.fromisoformat(cm["ts"])
                        except Exception:
                            ts = datetime.now()
                        rec.chat.append(ChatMessage(
                            ts=ts, sender=cm.get("sender", aid),
                            content=cm.get("content", ""),
                            direction=cm.get("direction", "in"),
                        ))
            current = ev.get("current_agent")
            self._state.current_room = current.lstrip("#") if isinstance(current, str) else None
            if self._state.current_room:
                self._state.chat_scroll = 0
            bare = self._state.current_room or ""
            if bare and bare in self._state.agents:
                self._state.agents[bare].is_current = True
            elif not self._state.current_room:
                agents = [a for a in self._state.agents if a != self._state.my_agent_id]
                if agents:
                    self._state.current_room = agents[0]
                    self._state.agents[agents[0]].is_current = True
            _sync_sidebar_cursor(self._state)
            room_names = sorted(self._state.rooms.keys())
            if self._state.current_room in room_names:
                self._state.connections_cursor = room_names.index(self._state.current_room)

        elif t == "spawn":
            aid = ev.get("agent_id", "")
            if aid:
                self._state.agents[aid] = AgentRecord(
                    agent_id          = aid,
                    agent_type        = _normalize_agent_type(ev.get("agent_type", "Agent")),
                    domain            = ev.get("domain", "default"),
                    platform          = ev.get("platform", "local"),
                    server_addr       = ev.get("server_addr", ""),
                    fsm_state         = ev.get("fsm_state", "—"),
                    avatar            = ev.get("avatar", ""),
                    model             = ev.get("model", ""),
                    vendor            = ev.get("vendor", ""),
                    competence_level  = ev.get("competence_level", "COMPETENT"),
                    competence_score  = float(ev.get("competence_score", 50.0)),
                    skills            = ev.get("skills", []),
                    tool_schemas      = list(ev.get("tool_schemas") or []),
                )
                role = str(ev.get("role") or "")
                behaviour = str(ev.get("behaviour") or "")
                if role:
                    self._state.agent_roles[aid] = role
                if behaviour:
                    self._state.agent_behaviours[aid] = behaviour
                # Auto-select first conversational agent (LLM etc.) as current chat target.
                rec = self._state.agents.get(aid)
                if (not self._state.current_room
                        and aid != self._state.my_agent_id
                        and rec is not None
                        and _is_conversational(rec)
                        and rec.agent_type not in ("HumanUser",)):
                    self._state.current_room = aid
                    rec.is_current = True
                    _sync_sidebar_cursor(self._state)

        elif t == "despawn":
            aid = ev.get("agent_id", "")
            self._state.agents.pop(aid, None)
            self._state.agent_roles.pop(aid, None)
            self._state.agent_behaviours.pop(aid, None)
            if self._state.current_room == aid:
                remaining = [a for a in self._state.agents if a != self._state.my_agent_id]
                self._state.current_room = remaining[0] if remaining else None

        elif t == "welcome":
            new_id = ev.get("your_id", "cli-user@1")
            self._state.my_agent_id = new_id
            # Register ourselves so we appear in the sidebar as the "You" entry
            if new_id not in self._state.agents:
                self._state.agents[new_id] = AgentRecord(
                    agent_id=new_id,
                    agent_type="HumanUser",
                    domain="cli",
                    platform="local",
                    skills=[],
                )
            # Clear current_room if it somehow points to our own ID
            if self._state.current_room == new_id:
                self._state.current_room = None

        elif t == "feed":
            try:
                ts = datetime.fromisoformat(ev["ts"])
            except Exception:
                ts = datetime.now()
            self._state.feed.append(FeedItem(
                ts=ts,
                event_type=ev.get("event_type", "message"),
                from_id=ev.get("from_id", ""),
                to_id=ev.get("to_id", ""),
                snippet=ev.get("snippet", ""),
                performative=ev.get("performative", "INFORM"),
            ))

        elif t == "chat":
            aid = ev.get("agent_id", "")
            rec = self._state.agents.get(aid)
            if rec:
                try:
                    ts = datetime.fromisoformat(ev["ts"])
                except Exception:
                    ts = datetime.now()
                _direction = ev.get("direction", "in")
                _content   = ev.get("content", "")
                rec.chat.append(ChatMessage(
                    ts=ts,
                    sender=ev.get("sender", aid),
                    content=_content,
                    direction=_direction,
                ))
        elif t == "reply":
            pass  # kept for forward-compatibility; no-op

        elif t == "fsm":
            aid = ev.get("agent_id", "")
            rec = self._state.agents.get(aid)
            if rec:
                rec.fsm_state    = ev.get("fsm_state", rec.fsm_state)
                rec.fsm_strategy = ev.get("fsm_strategy", rec.fsm_strategy)
                rec.fsm_loop     = ev.get("fsm_loop")

        elif t == "status":
            self._state.status_line  = ev.get("text", "")
            self._state.status_style = ev.get("style", "")

        elif t == "artifact":
            name = ev.get("name", "artifact")
            size = ev.get("size", "?")
            created_by = ev.get("created_by", "server")
            mime = ev.get("mime", "")
            self._state.status_line = f"Artifact received: {name} ({size} bytes)"
            self._state.status_style = "bold blue"
            # Note: no global feed entry — artifact events are scoped to the
            # creator agent's chat (inline image preview below) so they don't
            # appear in unrelated chats.
            # Inline-preview images in the creator agent's chat pane
            preview_b64 = ev.get("preview_data")
            preview_mime = ev.get("preview_mime", mime)
            if preview_b64 and isinstance(preview_b64, str) and str(preview_mime).startswith("image/"):
                try:
                    import base64 as _b64
                    img_bytes = _b64.b64decode(preview_b64)
                except Exception:
                    img_bytes = None
                if img_bytes:
                    rec = self._state.agents.get(created_by)
                    if rec is None and created_by in ("server",):
                        rec = self._state.agents.get(self._state.current_room or "")
                    if rec is not None:
                        rec.chat.append(ChatMessage(
                            ts=datetime.now(), sender=created_by,
                            content=f"📎 {name}", direction="in",
                            attachment=img_bytes,
                            attachment_mime=str(preview_mime),
                            attachment_name=str(name),
                        ))

        elif t in ("client_connect", "client_disconnect"):
            name = str(ev.get("name") or "")
            role = str(ev.get("role") or "")
            if role == "agent" and name:
                if t == "client_connect":
                    rec = self._state.agents.get(name)
                    if rec is None:
                        self._state.agents[name] = AgentRecord(
                            agent_id=name,
                            agent_type="ServiceAgent",
                            domain="services",
                            platform="remote",
                            skills=list(ev.get("skills", [])),
                        )
                    else:
                        rec.agent_type = "ServiceAgent"
                        rec.domain = "services"
                        rec.platform = "remote"
                        rec.skills = list(ev.get("skills", rec.skills))
                else:
                    self._state.agents.pop(name, None)
            icon = "🔌" if t == "client_connect" else "⛔"
            verb = "connected" if t == "client_connect" else "disconnected"
            peer = f"{name} @ {ev.get('addr', '?')}" if name else ev.get("addr", "?")
            self._state.feed.append(FeedItem(
                ts=datetime.now(), event_type="fed",
                from_id="server", to_id="",
                snippet=f"{icon} Client {verb}: {peer}",
            ))

        elif t == "room_join":
            room = ev.get("room", "")
            members = set(ev.get("members", []))
            self._state.rooms[room] = members
            if room not in self._state.rooms_chat:
                self._state.rooms_chat[room] = []
            self._state.feed.append(FeedItem(
                ts=datetime.now(), event_type="system",
                from_id="server", to_id="",
                snippet=f"🏠 Room #{room}: {', '.join(sorted(members))}",
            ))
            room_names = sorted(self._state.rooms.keys())
            if room in room_names:
                self._state.connections_cursor = room_names.index(room)
            if not self._state.current_room:
                self._state.current_room = room
                self._state.chat_scroll = 0

        elif t == "room_part":
            room = ev.get("room", "")
            member = ev.get("member", "")
            if room in self._state.rooms:
                self._state.rooms[room].discard(member)
                if not self._state.rooms[room]:
                    self._state.rooms.pop(room, None)
                    self._state.rooms_chat.pop(room, None)
            self._state.feed.append(FeedItem(
                ts=datetime.now(), event_type="system",
                from_id="server", to_id="",
                snippet=f"🚪 {member} left room #{room}",
            ))
            room_names = sorted(self._state.rooms.keys())
            if self._state.current_room == room and room not in self._state.rooms:
                self._state.current_room = room_names[0] if room_names else None
            if room_names:
                self._state.connections_cursor = min(self._state.connections_cursor, len(room_names) - 1)
            else:
                self._state.connections_cursor = 0

        elif t == "room_msg":
            room = ev.get("room", "")
            sender = ev.get("sender", "")
            content = ev.get("content", "")
            ts_str = ev.get("ts", "")
            try:
                msg_ts = datetime.fromisoformat(ts_str)
            except Exception:
                msg_ts = datetime.now()
            if room not in self._state.rooms_chat:
                self._state.rooms_chat[room] = []
            self._state.rooms_chat[room].append(ChatMessage(
                ts=msg_ts, sender=sender, content=content, direction="in"
            ))
            rec = self._state.agents.get(sender)
            if rec is not None:
                pass  # has_reply removed; reply always visible in chat

        elif t == "switch":
            new_target = ev.get("current_agent")
            if new_target is not None:
                for rec in self._state.agents.values():
                    rec.is_current = False
                self._state.current_room = new_target.lstrip("#")
                bare = self._state.current_room
                if bare in self._state.agents:
                    self._state.agents[bare].is_current = True
                _sync_sidebar_cursor(self._state)
                room_names = sorted(self._state.rooms.keys())
                if self._state.current_room in room_names:
                    self._state.connections_cursor = room_names.index(self._state.current_room)

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    def _send(self, msg: dict) -> None:
        line = (json.dumps(msg) + "\n").encode()
        self._writer.write(line)

    def _prompt_str(self) -> str:
        room = self._state.current_room
        srv = f" @{self._server_addr}" if self._server_addr else ""
        if room:
            display = f"#{room}" if room in self._state.rooms else room
            return f"[{display}{srv}]> "
        return f"[mars{srv}]> "

    def _cmd_agents_available(self) -> None:
        """Kept for backward compatibility — delegates to commands module."""
        _cmd_agents_available(self._state)

    # ------------------------------------------------------------------
    # Local command handler
    # ------------------------------------------------------------------

    async def _handle_command(self, line: str) -> bool:
        parts = line[1:].split()
        if not parts:
            return False
        cmd, *args = parts

        if cmd == "quit":
            return True
        elif cmd == "agents":
            if args and args[0] == "available":
                _cmd_agents_available(self._state)
            else:
                _cmd_agents(self._state)
        elif cmd == "switch":
            if args:
                target = args[0].lstrip("#")
                if target in self._state.rooms:
                    self._state.current_room = target
                    self._state.chat_scroll = 0
                    self._state.status_line = f"Switched to room #{target}"
                    room_names = sorted(self._state.rooms.keys())
                    self._state.connections_cursor = room_names.index(target)
                elif target in self._state.agents:
                    self._state.current_room = target
                    self._state.chat_scroll = 0
                    for rec in self._state.agents.values():
                        rec.is_current = False
                    self._state.agents[target].is_current = True
                    self._state.status_line = f"Switched to '{target}'"
                    _sync_sidebar_cursor(self._state)
                else:
                    self._state.status_line = f"Room or agent '{target}' not found."
            else:
                self._state.status_line = "Usage: /switch <room_or_agent_id>"
        elif cmd == "status":
            aid = args[0] if args else self._state.current_room
            if not aid:
                self._state.status_line = "No agent selected."
            else:
                rec = self._state.agents.get(aid)
                if rec:
                    loop = f"  loop={rec.fsm_loop}" if rec.fsm_loop else ""
                    self._state.status_line = (
                        f"{aid}: FSM={rec.fsm_state}  strategy={rec.fsm_strategy}{loop}"
                    )
                else:
                    self._state.status_line = f"Unknown agent '{aid}'"
        elif cmd == "avatar":
            if not args:
                self._state.status_line = "/avatar <number|emoji>"
            else:
                token = args[0]
                if token.isdigit():
                    idx = int(token) - 1
                    emoji = HUMAN_AVATARS[idx] if 0 <= idx < len(HUMAN_AVATARS) else token
                else:
                    emoji = token
                rec = self._state.agents.get("cli-user")
                if rec:
                    rec.avatar = emoji
                self._state.status_line = f"Avatar set to {emoji}"
        elif cmd == "verbose":
            aid = args[0] if args else self._state.current_room
            if not aid:
                self._state.status_line = "Usage: /verbose <agent_id>"
            else:
                rec = self._state.agents.get(aid)
                if rec:
                    rec.verbose = not rec.verbose
                    self._state.status_line = (
                        f"'{aid}' verbose {'ON 📢' if rec.verbose else 'OFF'}"
                    )
        elif cmd == "echo":
            if not args:
                self._state.status_line = f"echo mode: {self._state.echo_mode}  (usage: /echo <text|md|void>)"
            else:
                mode = _normalize_echo_mode(args[0])
                if mode is None:
                    self._state.status_line = f"Unknown echo mode '{args[0]}'. Use text | md | void."
                else:
                    self._state.echo_mode = mode
                    self._state.status_line = f"echo mode -> {mode}"
        elif cmd == "new":
            _cmd_new(self._state)
        elif cmd == "rewind":
            _cmd_rewind(self._state)
        elif cmd == "context":
            _cmd_context(self._state)
        elif cmd == "version":
            _cmd_version(self._state)
        elif cmd == "theme":
            _cmd_theme(self._state, " ".join(args))
        elif cmd == "share":
            _cmd_share(self._state, " ".join(args))
        elif cmd == "search":
            _cmd_search(self._state, " ".join(args))
        elif cmd == "copy":
            _cmd_copy(self._state, self._writer)
        elif cmd == "compact":
            _cmd_compact(self._state, self._writer)
        elif cmd == "instructions":
            _cmd_instructions(self._state, self._writer)
        elif cmd == "ask":
            _cmd_ask(self._state, self._writer, " ".join(args))
        elif cmd == "plan":
            _cmd_plan(self._state, self._writer, " ".join(args))
        elif cmd == "read":
            _cmd_read(self._state, " ".join(args))
        elif cmd == "help":
            _cmd_help(self._state)
        else:
            # Forward anything unknown to the server (/spawn, /stop, /join, /part, /list, …)
            self._send({"t": "cmd", "text": line})
        return False

    # ------------------------------------------------------------------
    # Background event receiver
    # ------------------------------------------------------------------

    async def _receive_events(self) -> None:
        try:
            while True:
                raw = await self._reader.readline()
                if not raw:
                    self._state.status_line = "⚠️  Disconnected from server"
                    self._state.status_style = "bold red"
                    break
                text = raw.decode().strip()
                if not text:
                    continue
                try:
                    ev = json.loads(text)
                    self._apply_event(ev)
                except Exception:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state.status_line = "⚠️  Connection error"
            self._state.status_style = "bold red"

    # ------------------------------------------------------------------
    # TUI loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        if _RICH and sys.stdin.isatty():
            await self._run_tui()
        else:
            await self._run_pipe()

    async def _run_tui(self) -> None:
        if self._console:
            self._console.clear()
        loop = asyncio.get_running_loop()
        input_queue: asyncio.Queue[str | None] = asyncio.Queue()

        def _read_input() -> None:
            buf = ""
            if sys.platform == "win32":
                import msvcrt

                def _scroll_key(sc: str) -> None:
                    focus = self._state.panel_focus
                    UP = ('H',)
                    DOWN = ('P',)

                    if sc in UP:
                        if focus == "chat":
                            self._state.chat_scroll = max(0, self._state.chat_scroll - 1)
                        elif focus == "sidebar":
                            _nav_sidebar(self._state, -1)
                        elif focus == "connections":
                            _nav_connections(self._state, -1)
                        elif focus == "mcp":
                            _nav_mcp(self._state, -1)
                    elif sc in DOWN:
                        if focus == "chat":
                            self._state.chat_scroll += 1
                        elif focus == "sidebar":
                            _nav_sidebar(self._state, +1)
                        elif focus == "connections":
                            _nav_connections(self._state, +1)
                        elif focus == "mcp":
                            _nav_mcp(self._state, +1)

                while True:
                    try:
                        ch = msvcrt.getwch()
                        if ch in ('\r', '\n'):
                            line, buf = buf, ""
                            with self._input_lock:
                                self._input_buffer = ""
                            loop.call_soon_threadsafe(input_queue.put_nowait, line)
                        elif ch == '\x03':
                            loop.call_soon_threadsafe(input_queue.put_nowait, None)
                            return
                        elif ch in ('\x08', '\x7f'):
                            buf = buf[:-1]
                            with self._input_lock:
                                self._input_buffer = buf
                        elif ch in ('\x00', '\xe0'):
                            sc = msvcrt.getwch()
                            _scroll_key(sc)
                        elif ch == '\t':  # Tab — cycle panel focus
                            order = self._renderer._PANEL_FOCUS_ORDER
                            cur = self._state.panel_focus
                            idx = order.index(cur) if cur in order else 0
                            self._state.panel_focus = order[(idx + 1) % len(order)]
                        else:
                            buf += ch
                            with self._input_lock:
                                self._input_buffer = buf
                    except Exception:
                        loop.call_soon_threadsafe(input_queue.put_nowait, None)
                        return
            else:
                import tty
                import termios
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd)
                    # Enable X10 mouse tracking for scroll wheel events
                    sys.stdout.write("\x1b[?1000h")
                    sys.stdout.flush()
                    while True:
                        ch = sys.stdin.read(1)
                        if ch in ('\r', '\n'):
                            line, buf = buf, ""
                            with self._input_lock:
                                self._input_buffer = ""
                            loop.call_soon_threadsafe(input_queue.put_nowait, line)
                        elif ch in ('\x03', '\x04'):
                            loop.call_soon_threadsafe(input_queue.put_nowait, None)
                            return
                        elif ch in ('\x7f', '\x08'):
                            buf = buf[:-1]
                            with self._input_lock:
                                self._input_buffer = buf
                        elif ch == '\t':  # Tab — cycle panel focus
                            order = self._renderer._PANEL_FOCUS_ORDER
                            cur = self._state.panel_focus
                            idx = order.index(cur) if cur in order else 0
                            self._state.panel_focus = order[(idx + 1) % len(order)]
                        elif ch == '\x1b':
                            ch2 = sys.stdin.read(1)
                            if ch2 == '[':
                                ch3 = sys.stdin.read(1)
                                focus = self._state.panel_focus
                                if ch3 == 'A':   # arrow up
                                    if focus == "chat":
                                        self._state.chat_scroll = max(0, self._state.chat_scroll - 1)
                                    elif focus == "sidebar":
                                        _nav_sidebar(self._state, -1)
                                    elif focus == "connections":
                                        _nav_connections(self._state, -1)
                                    elif focus == "mcp":
                                        _nav_mcp(self._state, -1)
                                elif ch3 == 'B':  # arrow down
                                    if focus == "chat":
                                        self._state.chat_scroll += 1
                                    elif focus == "sidebar":
                                        _nav_sidebar(self._state, +1)
                                    elif focus == "connections":
                                        _nav_connections(self._state, +1)
                                    elif focus == "mcp":
                                        _nav_mcp(self._state, +1)
                                elif ch3 == 'M':  # X10 mouse button event
                                    try:
                                        btn = ord(sys.stdin.read(1)) - 32
                                        sys.stdin.read(2)   # discard col, row
                                        focus = self._state.panel_focus
                                        if btn == 64:  # wheel up
                                            if focus == "chat":
                                                self._state.chat_scroll = max(0, self._state.chat_scroll - 1)
                                            elif focus == "sidebar":
                                                _nav_sidebar(self._state, -1)
                                            elif focus == "connections":
                                                _nav_connections(self._state, -1)
                                            elif focus == "mcp":
                                                _nav_mcp(self._state, -1)
                                        elif btn == 65:  # wheel down
                                            if focus == "chat":
                                                self._state.chat_scroll += 1
                                            elif focus == "sidebar":
                                                _nav_sidebar(self._state, +1)
                                            elif focus == "connections":
                                                _nav_connections(self._state, +1)
                                            elif focus == "mcp":
                                                _nav_mcp(self._state, +1)
                                    except Exception:
                                        pass
                        else:
                            buf += ch
                            with self._input_lock:
                                self._input_buffer = buf
                finally:
                    # Disable X10 mouse tracking before restoring terminal
                    sys.stdout.write("\x1b[?1000l")
                    sys.stdout.flush()
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)

        threading.Thread(target=_read_input, daemon=True).start()
        event_task = asyncio.create_task(self._receive_events())

        try:
            def _renderable() -> "Group":
                h = self._console.size.height if self._console else 40
                with self._input_lock:
                    buf = self._input_buffer
                return self._renderer.render_group(buf, self._prompt_str(), h)

            with Live(
                _renderable(),
                console=self._console,
                refresh_per_second=8,
                auto_refresh=True,
                screen=True,
            ) as live:
                while True:
                    live.update(_renderable())
                    try:
                        line = await asyncio.wait_for(input_queue.get(), timeout=0.125)
                    except asyncio.TimeoutError:
                        continue
                    if line is None:
                        break
                    line = line.strip()
                    self._state.reply_agent   = ""
                    self._state.reply_content = ""
                    if not line:
                        continue
                    if line.startswith("/"):
                        should_exit = await self._handle_command(line)
                        if should_exit:
                            break
                    elif line.startswith("!"):
                        _handle_bang_cmd(line, state=self._state)
                    else:
                        target = self._state.current_room
                        if not target:
                            self._state.status_line = "No active room — use /spawn on the server first."
                        elif target in self._state.rooms:
                            expanded = _expand_file_mentions(line)
                            room_name = target
                            if room_name not in self._state.rooms_chat:
                                self._state.rooms_chat[room_name] = []
                            self._state.rooms_chat[room_name].append(ChatMessage(
                                ts=datetime.now(), sender=self._state.my_agent_id or "you",
                                content=expanded, direction="out",
                            ))
                            self._state.chat_scroll = 0
                            self._send({"t": "msg", "target": f"#{target}", "text": expanded})
                        else:
                            expanded = _expand_file_mentions(line)
                            rec = self._state.agents.get(target)
                            if rec:
                                rec.chat.append(ChatMessage(
                                    ts=datetime.now(), sender=self._state.my_agent_id or "you",
                                    content=expanded, direction="out",
                                ))
                            self._state.chat_scroll = 0
                            self._send({"t": "msg", "target": target, "text": expanded})
        finally:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass

    async def _run_pipe(self) -> None:
        event_task = asyncio.create_task(self._receive_events())
        try:
            while True:
                try:
                    line = await asyncio.get_event_loop().run_in_executor(
                        None, sys.stdin.readline
                    )
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                if line.startswith("/"):
                    should_exit = await self._handle_command(line)
                    if should_exit:
                        break
                elif line.startswith("!"):
                    _handle_bang_cmd(line)
                else:
                    target = self._state.current_room
                    if not target:
                        self._state.status_line = "No active room — use /spawn on the server first."
                    elif target in self._state.rooms:
                        expanded = _expand_file_mentions(line)
                        room_name = target
                        if room_name not in self._state.rooms_chat:
                            self._state.rooms_chat[room_name] = []
                        self._state.rooms_chat[room_name].append(ChatMessage(
                            ts=datetime.now(), sender=self._state.my_agent_id or "you",
                            content=expanded, direction="out",
                        ))
                        self._send({"t": "msg", "target": f"#{target}", "text": expanded})
                    else:
                        expanded = _expand_file_mentions(line)
                        rec = self._state.agents.get(target)
                        if rec:
                            rec.chat.append(ChatMessage(
                                ts=datetime.now(), sender=self._state.my_agent_id or "you",
                                content=expanded, direction="out",
                            ))
                        self._send({"t": "msg", "target": target, "text": expanded})
                    await asyncio.sleep(3.0)
        finally:
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass

