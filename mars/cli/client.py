from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
from datetime import datetime

from mars.cli.commands import (
    _cmd_agents,
    _cmd_agents_available,
    _cmd_ask,
    _cmd_compact,
    _cmd_context,
    _cmd_copy,
    _cmd_help,
    _cmd_instructions,
    _cmd_new,
    _cmd_plan,
    _cmd_read,
    _cmd_rewind,
    _cmd_search,
    _cmd_share,
    _cmd_theme,
    _cmd_version,
    _expand_file_mentions,
    _handle_bang_cmd,
)
from mars.common.models import (
    HUMAN_AVATARS,
    ChatMessage,
    MARSState,
)
from mars.cli.events import apply_event
from mars.cli.nav import (
    _build_services_rows,
    _is_conversational,
    _nav_connections,
    _nav_services,
    _sync_sidebar_cursor,
)
from mars.cli.renderer import MARSRenderer
from mars.cli.utils import _normalize_echo_mode
from mars.common.wire import encode_frame, iter_frames

try:
    from rich.console import Console, Group
    from rich.live import Live
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
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
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
        apply_event(self._state, ev)
        # After receiving the initial state frame, request model lists
        if ev.get("t") == "state":
            self._send({"t": "cmd", "cmd": "get_models"})

    # ------------------------------------------------------------------
    # Send helpers
    # ------------------------------------------------------------------

    def _send(self, msg: dict) -> None:
        line = encode_frame(msg)
        self._writer.write(line)

    def _activate_services_selection(self) -> str | None:
        """Activate the currently selected row in the services panel.

        Returns a command string to submit (e.g. '/spawn ollama qwen3:4b'),
        or None if the selection was handled internally (expand/collapse).
        """
        s = self._state
        rows = _build_services_rows(s)
        if not rows or s.services_cursor >= len(rows):
            return None
        row = rows[s.services_cursor]
        if row[0] == "provider":
            # Toggle expand/collapse
            provider = row[1]
            s.services_expanded[provider] = not s.services_expanded.get(provider, False)
            return None
        if row[0] == "model":
            provider, model_id = row[1], row[2]
            return f"/spawn {provider} {model_id}"
        return None

    def _prompt_str(self) -> str:
        target = self._state.current_agent
        srv = f" @{self._server_addr}" if self._server_addr else ""
        if target:
            return f"[{target}{srv}]> "
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
                rec = self._state.agents.get(target)
                if rec and _is_conversational(rec):
                    self._state.current_agent = target
                    self._state.chat_scroll = 0
                    for rec in self._state.agents.values():
                        rec.is_current = False
                    self._state.agents[target].is_current = True
                    self._state.status_line = f"Switched to '{target}'"
                    _sync_sidebar_cursor(self._state)
                elif rec is not None:
                    self._state.status_line = f"'{target}' is a service agent, not a chat target"
                else:
                    self._state.status_line = f"Agent '{target}' not found."
            else:
                self._state.status_line = "Usage: /switch <agent_id>"
        elif cmd == "status":
            aid = args[0] if args else self._state.current_agent
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
            aid = args[0] if args else self._state.current_agent
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
            async for ev in iter_frames(self._reader):
                with contextlib.suppress(Exception):
                    self._apply_event(ev)
            self._state.status_line = "⚠️  Disconnected from server"
            self._state.status_style = "bold red"
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
                        elif focus == "services":
                            _nav_services(self._state, -1)
                        elif focus == "connections":
                            _nav_connections(self._state, -1)
                    elif sc in DOWN:
                        if focus == "chat":
                            self._state.chat_scroll += 1
                        elif focus == "services":
                            _nav_services(self._state, +1)
                        elif focus == "connections":
                            _nav_connections(self._state, +1)

                while True:
                    try:
                        ch = msvcrt.getwch()
                        if ch in ('\r', '\n'):
                            # If services panel is focused and buffer is empty, activate selection
                            if self._state.panel_focus == "services" and not buf:
                                cmd = self._activate_services_selection()
                                if cmd is not None:
                                    loop.call_soon_threadsafe(input_queue.put_nowait, cmd)
                                continue
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
                import termios
                import tty
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
                            # If services panel is focused and buffer is empty, activate selection
                            if self._state.panel_focus == "services" and not buf:
                                cmd = self._activate_services_selection()
                                if cmd is not None:
                                    loop.call_soon_threadsafe(input_queue.put_nowait, cmd)
                                continue
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
                                    elif focus == "services":
                                        _nav_services(self._state, -1)
                                    elif focus == "connections":
                                        _nav_connections(self._state, -1)
                                elif ch3 == 'B':  # arrow down
                                    if focus == "chat":
                                        self._state.chat_scroll += 1
                                    elif focus == "services":
                                        _nav_services(self._state, +1)
                                    elif focus == "connections":
                                        _nav_connections(self._state, +1)
                                elif ch3 == 'M':  # X10 mouse button event
                                    try:
                                        btn = ord(sys.stdin.read(1)) - 32
                                        sys.stdin.read(2)   # discard col, row
                                        focus = self._state.panel_focus
                                        if btn == 64:  # wheel up
                                            if focus == "chat":
                                                self._state.chat_scroll = max(0, self._state.chat_scroll - 1)
                                            elif focus == "services":
                                                _nav_services(self._state, -1)
                                            elif focus == "connections":
                                                _nav_connections(self._state, -1)
                                        elif btn == 65:  # wheel down
                                            if focus == "chat":
                                                self._state.chat_scroll += 1
                                            elif focus == "services":
                                                _nav_services(self._state, +1)
                                            elif focus == "connections":
                                                _nav_connections(self._state, +1)
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
            def _renderable() -> Group:
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
                    except TimeoutError:
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
                        target = self._state.current_agent
                        if not target:
                            self._state.status_line = "No active agent — use /spawn on the server first."
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
            with contextlib.suppress(asyncio.CancelledError):
                await event_task

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
                    target = self._state.current_agent
                    if not target:
                        self._state.status_line = "No active agent — use /spawn on the server first."
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
            with contextlib.suppress(asyncio.CancelledError):
                await event_task
