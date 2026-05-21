from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mars.client.cli.models import (
    MARSState, AgentRecord, ChatMessage, FeedItem,
    AGENT_EMOJIS, EVENT_ICONS, HUMAN_AVATARS,
    _sidebar_agent_ids, _is_conversational, _CONVERSATIONAL_TYPES,
    _mcp_agent_ids,
)
from mars.client.cli.utils import _time_ago

try:
    from rich.console import Console, Group
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text
    _RICH = True
except ImportError:
    _RICH = False
    Console = None  # type: ignore[misc,assignment]

try:
    from mars.client.cli.math_renderer import preprocess_math as _preprocess_math
except Exception:
    def _preprocess_math(content: str) -> str:  # type: ignore[misc]
        return content

class MARSRenderer:
    def __init__(self, state: MARSState) -> None:
        self._s = state

    # Panel widths — change here to resize both side panels at once.
    SIDE_PANEL_WIDTH: int = 36

    # Braille spinner frames cycled when an agent is THINKING.
    _THINKING_SPINNER = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    # -- Sidebar (Slack-style agent list) ------------------------------------


    # Pure CLI in-process agents: echo bots only.
    # The user's own identity (🏠) is determined dynamically via state.my_agent_id.
    _ECHO_AGENTS = frozenset(
        ("echo-text", "echo-md", "echo-void")
    )

    # Keep _CLI_LOCAL_AGENTS as the union for addr-suppression tests
    _CLI_LOCAL_AGENTS = frozenset(
        ("echo-text", "echo-md", "echo-void", "cli-user@1")
    )

    # Agent IDs pinned at the top of the sidebar (in this order).
    _PINNED_AGENTS: tuple = ()  # echo bots no longer shown in sidebar

    def render_sidebar(self, height: int | None = None) -> Panel:
        """Top-left panel: conversational agents (LLM, human, bridge)."""
        s = self._s
        text = Text()
        nav_ids = _sidebar_agent_ids(s)  # conversational only — used for cursor indexing
        conv_agents = [(aid, s.agents[aid]) for aid in nav_ids if aid in s.agents]
        nav_total = len(nav_ids)
        scroll = max(0, min(s.sidebar_scroll, max(0, nav_total - 1)))
        s.sidebar_scroll = scroll
        # track visible window size for scroll-follow in _nav_sidebar
        if height is not None:
            s.sidebar_visible_height = max(1, height - 2)
        # clamp cursor to conversational range
        s.sidebar_cursor = max(0, min(s.sidebar_cursor, max(0, nav_total - 1)))
        # one spinner frame for all THINKING agents in this render pass
        _spin = self._THINKING_SPINNER[int(time.monotonic() * 8) % len(self._THINKING_SPINNER)]

        def _render_row(idx: int, aid: str, rec: "AgentRecord") -> None:
            is_cursor = (idx == s.sidebar_cursor)
            is_error = rec.fsm_state in ("ERROR", "CRASHED", "FAILED", "BLOCKED")
            emoji = "⚠️" if is_error else s.emoji(aid)
            is_thinking = rec.fsm_state == "THINKING"
            dot_color = (
                "red"   if is_error
                else "blue"  if is_thinking
                else "green" if rec.fsm_state in ("IDLE", "WAITING", "—", "")
                else "grey50"
            )
            label_style = "bold yellow" if rec.is_current else "white"
            text.append("►" if (is_cursor and s.panel_focus == "sidebar") else " ", style="bold cyan" if (is_cursor and s.panel_focus == "sidebar") else "")
            text.append(_spin if is_thinking else "●", style="bold blue" if is_thinking else dot_color)
            text.append(f" {emoji} ")
            text.append(aid, style=label_style)
            if rec.model:
                text.append(f"  {rec.model.split('/')[-1][:14]}", style="dim")
            text.append("\n")

        for idx, (aid, rec) in enumerate(conv_agents):
            if idx < scroll:
                continue
            _render_row(idx, aid, rec)

        if not text.plain:
            text.append("  [dim]No agents yet — /spawn to start[/dim]\n")

        peers = len(s.federation_peers)
        agent_label = f"{nav_total} agent{'s' if nav_total != 1 else ''}"
        subtitle = f"[dim]{agent_label}"
        if peers:
            subtitle += f" · {peers} peer(s)"
        if scroll > 0:
            subtitle += f" ↓{scroll}"
        subtitle += "[/dim]"
        border_style = "green" if s.panel_focus == "sidebar" else "blue"
        return Panel(
            text,
            title="[bold cyan]🤖 Agents[/bold cyan]",
            subtitle=subtitle,
            border_style=border_style,
            padding=(0, 0),
            height=height,
        )

    def render_mcp_panel(self, height: int | None = None) -> Panel:
        """Bottom-left panel: MCP service agents (collapsed) with selected one expanded."""
        s = self._s
        is_focused = s.panel_focus == "mcp"
        _spin = self._THINKING_SPINNER[int(time.monotonic() * 8) % len(self._THINKING_SPINNER)]

        svc_ids = _mcp_agent_ids(s)
        max_rows = max(1, (height - 2) if height else 999)

        # Track visible height for scroll-follow (server count, not row count)
        if height is not None:
            s.mcp_visible_height = max(1, height - 2)

        # Clamp cursor and scroll to valid range
        if svc_ids:
            s.mcp_cursor = max(0, min(s.mcp_cursor, len(svc_ids) - 1))
            s.mcp_scroll = max(0, min(s.mcp_scroll, len(svc_ids) - 1))

        text = Text()

        if not svc_ids:
            text.append("  ", style="")
            text.append("No MCP servers active\n", style="dim")
            text.append("  ", style="")
            text.append("/spawn <name> to activate\n", style="dim")
        else:
            rows_used = 0
            for i_abs, aid in enumerate(svc_ids):
                if i_abs < s.mcp_scroll:
                    continue
                if rows_used >= max_rows:
                    break

                rec = s.agents.get(aid)
                if rec is None:
                    continue

                is_selected = is_focused and (i_abs == s.mcp_cursor)
                is_error = rec.fsm_state in ("ERROR", "CRASHED", "FAILED", "BLOCKED")
                is_thinking = rec.fsm_state == "THINKING"

                dot_color = (
                    "red"    if is_error
                    else "blue"   if is_thinking
                    else "green"  if rec.fsm_state in ("IDLE", "WAITING", "—", "")
                    else "grey50"
                )
                emoji = "⚠️" if is_error else s.emoji(aid)
                dot = _spin if is_thinking else "●"
                dot_style = "bold blue" if is_thinking else dot_color

                tools: list[dict] = getattr(rec, "tool_schemas", []) or []
                has_children = bool(tools)

                # ▶ collapsed  ▼ expanded  (space when no children)
                cursor_ch = "►" if is_selected else " "
                expand_ch = ""
                if has_children:
                    expand_ch = " ▼" if is_selected else " ▶"

                # Header row
                text.append(cursor_ch, style="bold cyan" if is_selected else "")
                text.append(dot, style=dot_style)
                text.append(f" {emoji} ")
                short_id = aid if len(aid) <= 19 else aid[:16] + "…"
                text.append(short_id, style="bold white" if is_selected else "white")
                text.append(expand_ch, style="dim cyan")
                text.append("\n")
                rows_used += 1

                # Expanded: only real tool names (no internal routing keywords)
                if is_selected and has_children:
                    for tool in tools:
                        if rows_used >= max_rows:
                            break
                        name = tool.get("name", "?")[:20]
                        text.append(f"   ⚙ {name}\n", style="dim cyan")
                        rows_used += 1

        total_tools = sum(
            len(getattr(s.agents[aid], "tool_schemas", []) or [])
            for aid in svc_ids if aid in s.agents
        )
        subtitle = f"[dim]{len(svc_ids)} server{'s' if len(svc_ids) != 1 else ''}"
        if total_tools:
            subtitle += f" · {total_tools} tool{'s' if total_tools != 1 else ''}"
        subtitle += "[/dim]"

        border_style = "green" if is_focused else "blue"
        return Panel(
            text,
            title="[bold magenta]🔧 MCP Servers[/bold magenta]",
            subtitle=subtitle,
            border_style=border_style,
            padding=(0, 0),
            height=height,
        )

    FEED_LINES = 14          # fallback line count when no height is passed
    _CHAT_WINDOW_MIN = 4     # never show fewer than this many messages
    _REPLY_PANEL_H = 7       # rows reserved for the reply panel when visible
    # Lines of overhead per panel (2 borders + 1 title + 1 padding row)
    _PANEL_OVERHEAD = 4
    _PANEL_FOCUS_ORDER = ("sidebar", "mcp", "chat", "connections")  # Tab cycle order

    @staticmethod
    def _image_to_halfblocks(data: bytes, max_width: int = 60) -> "Text | None":
        """Render an image to Unicode half-block characters.

        Each output line shows two image rows: the top pixel becomes the
        character foreground (▀) and the bottom pixel becomes the background.
        Works in any terminal that supports 24-bit colour (most modern ones,
        including Windows Terminal).
        """
        try:
            import io as _io
            from PIL import Image
        except Exception:
            return None
        try:
            img = Image.open(_io.BytesIO(data)).convert("RGB")
        except Exception:
            return None
        w, h = img.size
        if w > max_width:
            new_w = max_width
            new_h = max(2, int(h * new_w / w))
            img = img.resize((new_w, new_h))
        if img.height % 2 == 1:
            img = img.crop((0, 0, img.width, img.height - 1))
        px = img.load()
        text = Text()
        for y in range(0, img.height, 2):
            for x in range(img.width):
                r1, g1, b1 = px[x, y]
                r2, g2, b2 = px[x, y + 1]
                text.append(
                    "▀",
                    style=Style(color=f"rgb({r1},{g1},{b1})", bgcolor=f"rgb({r2},{g2},{b2})"),
                )
            text.append("\n")
        return text

    def _render_chat_blocks(
        self,
        msgs: list["ChatMessage"],
        scroll: int,
        agent_emoji: str = "",
        room_mode: bool = False,
        window: int | None = None,
    ) -> tuple[list[Any], int]:
        """Return (blocks, total) for a chat message list.

        Used by both 1:1 agent chat and group room chat so rendering is
        identical — the only difference is that room mode always uses
        ``cm.sender`` for the label instead of a fixed agent name.
        """
        s = self._s
        w = window if window is not None else self._CHAT_WINDOW_MIN
        total = len(msgs)
        end = max(0, total - scroll)
        start = max(0, end - w)
        recent = msgs[start:end]
        user_emoji = s.emoji(s.my_agent_id)
        blocks: list[Any] = []
        for cm in recent:
            ts = cm.ts.strftime("%H:%M:%S")
            if cm.direction == "system":
                blocks.append(Text(f"  {cm.content}", style="dim italic"))
                blocks.append(Text(""))
                continue
            if cm.direction == "out":
                sender_em = s.emoji(cm.sender) if room_mode else user_emoji
                header = Text(f"{sender_em} {cm.sender}  {ts}", style="bold green")
                body = Text(cm.content, style="white", overflow="fold", no_wrap=False)
            else:
                if s.echo_mode == "void":
                    continue
                # Always attribute by actual sender — works for both 1:1 and group
                sender_em = s.emoji(cm.sender) if room_mode else agent_emoji
                sender_label = f"{sender_em} {cm.sender}"
                _err_prefixes = ("🚫", "⚠️", "❌")
                if cm.content.startswith(_err_prefixes):
                    _eh = Text(f"{sender_label}  {ts}", style="bold red")
                    _eb = Text(cm.content, style="red", overflow="fold", no_wrap=False)
                    blocks.append(Panel(Group(_eh, _eb), border_style="red", padding=(0, 1)))
                    blocks.append(Text(""))
                    continue
                header = Text(f"{sender_label}  {ts}", style="bold cyan")
                if s.echo_mode == "text":
                    body = Text(cm.content, style="white", overflow="fold", no_wrap=False)
                else:
                    body = Markdown(
                        _preprocess_math(cm.content),
                        code_theme="monokai",
                        justify="left",
                    )
            blocks.append(header)
            blocks.append(body)
            if getattr(cm, "attachment", None) and getattr(cm, "attachment_mime", "").startswith("image/"):
                img_text = self._image_to_halfblocks(cm.attachment, max_width=60)
                if img_text is not None:
                    if getattr(cm, "attachment_name", ""):
                        blocks.append(Text(f"📎 {cm.attachment_name}", style="dim"))
                    blocks.append(img_text)
            blocks.append(Text(""))
        return blocks, total

    def render_feed(self, height: int | None = None) -> Panel:
        s = self._s
        border_style = "green" if s.panel_focus == "chat" else "blue"

        # Messages that fit: each message takes ~3 rows (header + body + blank).
        # Use actual panel content area when height is known, else fall back.
        content_h = max(self._CHAT_WINDOW_MIN * 3, (height - self._PANEL_OVERHEAD)) if height else self.FEED_LINES
        window = max(self._CHAT_WINDOW_MIN, content_h // 3)

        # --- Room chat view ---
        if s.current_room and s.current_room in s.rooms:
            room_name = s.current_room
            room_msgs = list(s.rooms_chat.get(room_name, deque()))
            total = len(room_msgs)
            max_scroll = max(0, total - window)
            scroll = max(0, min(s.chat_scroll, max_scroll))
            blocks, total = self._render_chat_blocks(room_msgs, scroll, room_mode=True, window=window)
            if not blocks:
                members = sorted(s.rooms.get(room_name, set()))
                if members:
                    hint = f"Members: {', '.join(members)}"
                else:
                    hint = "Empty room — use /join <room> to add members"
                blocks.append(Text(hint, style="dim"))
            scroll_hint = (
                f" [dim]↑{scroll} older  ↓=newer[/dim]" if scroll > 0
                else " [dim]↑=older[/dim]" if total > window
                else ""
            )
            members_set = s.rooms.get(room_name, set())
            others = sorted(members_set - {s.my_agent_id})
            n = len(others)
            label = others[0] if n == 1 else f"{n} members" if n > 1 else "just you"
            title = (
                f"[bold]💬 #{room_name}  {label}[/bold]"
                f"{scroll_hint} [dim cyan][echo:{s.echo_mode}][/dim cyan]"
            )
            return Panel(
                Group(*blocks),
                title=title,
                border_style=border_style,
                padding=(0, 1),
                height=height if height is not None else self.FEED_LINES + self._PANEL_OVERHEAD,
            )

        # --- Direct agent chat (service agents without a room) ---
        if s.current_room and s.current_room in s.agents and s.current_room != s.my_agent_id:
            rec = s.agents[s.current_room]
            if not _is_conversational(rec):
                agent_msgs = list(rec.chat)
                total = len(agent_msgs)
                max_scroll = max(0, total - window)
                scroll = max(0, min(s.chat_scroll, max_scroll))
                blocks, total = self._render_chat_blocks(agent_msgs, scroll, room_mode=False, window=window)
                if not blocks:
                    blocks.append(Text(
                        f"Direct chat with {s.current_room} — type a message to start.",
                        style="dim",
                    ))
                scroll_hint = (
                    f" [dim]↑{scroll} older  ↓=newer[/dim]" if scroll > 0
                    else " [dim]↑=older[/dim]" if total > window
                    else ""
                )
                avatar = rec.avatar or s.emoji(s.current_room)
                title = (
                    f"[bold]💬 {avatar}{s.current_room}[/bold]"
                    f"{scroll_hint} [dim cyan][echo:{s.echo_mode}][/dim cyan]"
                )
                return Panel(
                    Group(*blocks),
                    title=title,
                    border_style=border_style,
                    padding=(0, 1),
                    height=height if height is not None else self.FEED_LINES + self._PANEL_OVERHEAD,
                )

        # --- Global activity feed (nothing selected) ---
        text = Text(overflow="fold", no_wrap=False)
        items = list(s.feed)
        lines_g: list[tuple[str, str]] = []
        for item in items:
            icon = EVENT_ICONS.get(item.event_type, "•")
            ts   = item.ts.strftime("%H:%M:%S")
            if item.event_type in ("message", "reply"):
                ef = s.emoji(item.from_id)
                et = s.emoji(item.to_id)
                lines_g.append((f"{icon} {ts} ", "dim"))
                lines_g.append((f"{ef}{item.from_id} → {et}{item.to_id}", "cyan"))
                lines_g.append((f"   {item.snippet}", "dim"))
            elif item.event_type == "state":
                lines_g.append((f"{icon} {ts}  {item.snippet}", "blue"))
            else:
                lines_g.append((f"{icon} {ts}  {item.snippet}", "dim yellow"))
        # Show as many lines as the panel content area allows
        feed_lines = content_h
        visible = lines_g[-feed_lines:]
        for content, style in visible:
            text.append(content + "\n", style=style)
        for _ in range(feed_lines - len(visible)):
            text.append("\n")
        return Panel(
            text,
            title="[bold]Activity Feed[/bold]",
            border_style=border_style,
            padding=(0, 1),
            height=height if height is not None else self.FEED_LINES + self._PANEL_OVERHEAD,
        )

    # -- Full header ---------------------------------------------------------

    def print_header(self, console: "Console") -> None:
        console.print(self.render_feed())
        console.print(self.render_sidebar())
        console.print(Rule(style="dim"))

    # -- Reply panel (raised-hand acknowledgement) ---------------------------

    def render_reply_panel(self) -> "Panel | None":
        agent_id = self._s.reply_agent
        content  = self._s.reply_content
        if not agent_id or not content:
            return None
        renderable: "Any" = (
            Markdown(_preprocess_math(content), code_theme="monokai")
            if _RICH else content
        )
        return Panel(
            renderable,
            title=f"[bold cyan]✋  {agent_id}[/bold cyan]",
            border_style="blue",
            padding=(0, 2),
        )

    def render_connections(self, height: int | None = None) -> Panel:
        """Right panel: group rooms and their members."""
        s = self._s
        text = Text()
        _spin = self._THINKING_SPINNER[int(time.monotonic() * 8) % len(self._THINKING_SPINNER)]

        rooms = s.rooms
        sorted_rooms = sorted(rooms.items())
        if height is not None:
            s.connections_visible_height = max(1, height - 2)
        visible_rows = max(1, s.connections_visible_height)

        if sorted_rooms:
            s.connections_cursor = max(0, min(s.connections_cursor, len(sorted_rooms) - 1))
            s.connections_scroll = max(0, min(s.connections_scroll, len(sorted_rooms) - 1))
            text.append(" ─ rooms ─\n", style="bold cyan")
            for i, (room_name, members) in enumerate(sorted_rooms):
                if i < s.connections_scroll:
                    continue
                if i >= s.connections_scroll + visible_rows:
                    break
                is_active = s.current_room == room_name
                is_cursor = (s.panel_focus == "connections") and (i == s.connections_cursor)
                if is_active:
                    arrow = "►"
                    room_style = "bold yellow"
                elif is_cursor:
                    arrow = "›"
                    room_style = "bold white"
                else:
                    arrow = " "
                    room_style = "white"
                text.append(f"{arrow} 💬 #{room_name}\n", style=room_style)
                for mid in sorted(members):
                    mem_em = s.emoji(mid)
                    role_tag = f" [{s.agent_roles[mid]}]" if mid in s.agent_roles else ""
                    mem_rec = s.agents.get(mid)
                    if mem_rec:
                        is_err = mem_rec.fsm_state in ("ERROR", "CRASHED", "FAILED", "BLOCKED")
                        is_thinking = mem_rec.fsm_state == "THINKING"
                        if is_err:
                            dot = ("●", "red")
                        elif is_thinking:
                            dot = (_spin, "bold blue")
                        else:
                            dot = ("●", "green")
                    else:
                        dot = ("●", "green")
                    text.append("   ", style="dim")
                    text.append(dot[0], style=dot[1])
                    text.append(f" {mem_em} {mid}{role_tag}\n", style="dim")
                text.append("\n")
        else:
            text.append("  No rooms yet — use /spawn or /join to create one\n", style="dim")

        border_style = "green" if s.panel_focus == "connections" else "blue"
        return Panel(
            text,
            title="[bold green]💬 Rooms & Comms[/bold green]",
            border_style=border_style,
            padding=(0, 0),
            height=height,
        )

    # -- Command output panel ------------------------------------------------
    # (removed — command output shown inline in chat feed)

    # -- Live renderable (used by rich.live.Live) ----------------------------

    def render_group(self, input_buf: str = "", prompt: str = "> ",
                     console_height: int = 40) -> "Group":
        # Available height for panels: total minus prompt panel (3 lines)
        panel_h = max(4, console_height - 3)

        # Right-side content: feed fills the available height
        reply_panel = self.render_reply_panel()
        if reply_panel:
            feed_h = max(4, panel_h - self._REPLY_PANEL_H)
            right_content = Group(self.render_feed(height=feed_h), reply_panel)
        else:
            right_content = self.render_feed(height=panel_h)

        # Left column: Agents panel (top ~60 %) stacked above MCP panel (bottom ~40 %).
        agents_h = max(4, int(panel_h * 0.6))
        mcp_h    = max(4, panel_h - agents_h)
        left_content = Group(
            self.render_sidebar(height=agents_h),
            self.render_mcp_panel(height=mcp_h),
        )

        # Three-column layout: [agents+mcp] | feed | connections.
        # `no_wrap=True` on the side columns prevents long agent IDs or
        # connection labels from wrapping and pushing the row taller than the
        # configured panel height (a known cause of layout corruption when
        # markdown chat replies are also present).
        layout = Table.grid(expand=True, padding=0)
        layout.add_column(width=self.SIDE_PANEL_WIDTH, no_wrap=True, overflow="ellipsis")   # left (agents + mcp)
        layout.add_column(ratio=1, overflow="fold")                                          # main feed
        layout.add_column(width=self.SIDE_PANEL_WIDTH, no_wrap=True, overflow="ellipsis")   # connections
        layout.add_row(left_content, right_content, self.render_connections(height=panel_h))

        # Prompt at the bottom — status_line shown as panel title so command
        # feedback (✅ Copied, ⏪ Rewound, …) is always visible.
        status       = self._s.status_line
        status_style = self._s.status_style or "dim"
        prompt_text = Text()
        prompt_text.append(prompt, style="bold green")
        prompt_text.append(input_buf + "▌")
        prompt_panel = Panel(
            prompt_text,
            title=Text(status, style=status_style) if status else None,
            border_style="green",
            padding=(0, 1),
        )

        return Group(layout, prompt_panel)
