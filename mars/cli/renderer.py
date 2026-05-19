from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mars.cli.models import (
    MARSState, AgentRecord, ChatMessage, FeedItem,
    AGENT_EMOJIS, EVENT_ICONS, HUMAN_AVATARS,
    _sidebar_agent_ids, _is_conversational, _CONVERSATIONAL_TYPES,
)
from mars.cli.utils import _time_ago

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

class MARSRenderer:
    def __init__(self, state: MARSState) -> None:
        self._s = state

    # Panel widths — change here to resize both side panels at once.
    SIDE_PANEL_WIDTH: int = 36

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
        s = self._s
        text = Text()
        nav_ids = _sidebar_agent_ids(s)  # conversational only — used for cursor indexing
        conv_agents = [(aid, s.agents[aid]) for aid in nav_ids if aid in s.agents]
        svc_agents = [
            (aid, rec) for aid, rec in sorted(s.agents.items())
            if not _is_conversational(rec) and rec.agent_type != "EchoBot"
        ]
        nav_total = len(nav_ids)
        scroll = max(0, min(s.sidebar_scroll, max(0, nav_total - 1)))
        s.sidebar_scroll = scroll
        # track visible window size for scroll-follow in _nav_sidebar
        if height is not None:
            s.sidebar_visible_height = max(1, height - 2)
        # clamp cursor to conversational range
        s.sidebar_cursor = max(0, min(s.sidebar_cursor, max(0, nav_total - 1)))
        def _render_row(idx: int, aid: str, rec: "AgentRecord", *, dim: bool = False) -> None:
            is_cursor = (idx == s.sidebar_cursor) and not dim
            is_error = rec.fsm_state in ("ERROR", "CRASHED", "FAILED", "BLOCKED")
            is_self = (aid == s.my_agent_id)
            emoji = "⚠️" if is_error else ("😊" if is_self else s.emoji(aid))
            dot_color = (
                "red"    if is_error
                else "blue"   if rec.fsm_state == "THINKING"
                else "yellow" if rec.has_reply
                else "green"  if rec.fsm_state in ("IDLE", "WAITING", "—", "")
                else "grey50"
            )
            label_style = "dim" if dim else ("bold yellow" if rec.is_current else "white")
            if is_cursor and s.panel_focus == "sidebar":
                text.append("►", style="bold cyan")
            else:
                text.append(" ")
            text.append("●", style="grey50" if dim else dot_color)
            text.append(f" {emoji} ")
            text.append(aid, style=label_style)
            if not dim:
                if rec.model:
                    short_model = rec.model.split("/")[-1][:14]
                    text.append(f"  {short_model}", style="dim")
                behaviour = s.agent_behaviours.get(aid, "")
                if behaviour == "proactive":
                    text.append("  ⏰", style="dim cyan")
                elif behaviour == "reactive":
                    text.append("  ⚡", style="dim yellow")
            text.append("\n")

        for idx, (aid, rec) in enumerate(conv_agents):
            if idx < scroll:
                continue
            _render_row(idx, aid, rec)

        if svc_agents:
            text.append(" ─ services ─\n", style="dim")
            for aid, rec in svc_agents:
                _render_row(-1, aid, rec, dim=True)

        if not text.plain:
            text.append(" [dim]No agents yet[/dim]\n")

        peers = len(s.federation_peers)
        agent_label = f"{nav_total} agent{'s' if nav_total != 1 else ''}"
        subtitle = f"[dim]{agent_label}"
        if svc_agents:
            subtitle += f" · {len(svc_agents)} services"
        if peers:
            subtitle += f" · {peers} peer(s)"
        subtitle += "[/dim]"
        if scroll > 0:
            subtitle += f" [dim]↓{scroll}[/dim]"
        border_style = "yellow" if s.panel_focus == "sidebar" else "cyan"
        return Panel(
            text,
            title="[bold cyan]🤖 Agents[/bold cyan]",
            subtitle=subtitle,
            border_style=border_style,
            padding=(0, 0),
            height=height,
        )

    FEED_LINES = 14  # fixed visible line count (excluding panel border)
    _CHAT_WINDOW = 6  # messages visible at once
    _PANEL_FOCUS_ORDER = ("sidebar", "chat", "connections")  # Tab cycle order

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
    ) -> tuple[list[Any], int]:
        """Return (blocks, total) for a chat message list.

        Used by both 1:1 agent chat and group room chat so rendering is
        identical — the only difference is that room mode always uses
        ``cm.sender`` for the label instead of a fixed agent name.
        """
        s = self._s
        total = len(msgs)
        end = max(0, total - scroll)
        start = max(0, end - self._CHAT_WINDOW)
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
                    body = Markdown(cm.content, code_theme="monokai", justify="left")
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
        border_style = "yellow" if s.panel_focus == "chat" else "blue"

        # --- Room chat view (the only chat mode) ---
        if s.current_agent and s.current_agent.startswith("#"):
            room_name = s.current_agent[1:]
            room_msgs = list(s.rooms_chat.get(room_name, deque()))
            total = len(room_msgs)
            max_scroll = max(0, total - 1)
            scroll = max(0, min(s.chat_scroll, max_scroll))
            blocks, total = self._render_chat_blocks(room_msgs, scroll, room_mode=True)
            if not blocks:
                members = sorted(s.rooms.get(room_name, set()))
                if members:
                    hint = f"Members: {', '.join(members)}"
                else:
                    hint = "Empty room — use /join <room> to add members"
                blocks.append(Text(hint, style="dim"))
            scroll_hint = (
                f" [dim]↑{scroll} older  ↓=newer[/dim]" if scroll > 0
                else " [dim]↑=older[/dim]" if total > self._CHAT_WINDOW
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
                height=height if height is not None else self.FEED_LINES + 4,
            )

        # --- Direct agent chat (service agents only — conversational agents always use rooms) ---
        if s.current_agent and s.current_agent in s.agents and s.current_agent != s.my_agent_id:
            rec = s.agents[s.current_agent]
            if not _is_conversational(rec):
                agent_msgs = list(rec.chat)
                total = len(agent_msgs)
                max_scroll = max(0, total - 1)
                scroll = max(0, min(s.chat_scroll, max_scroll))
                blocks, total = self._render_chat_blocks(agent_msgs, scroll, room_mode=False)
                if not blocks:
                    blocks.append(Text(
                        f"Direct chat with {s.current_agent} — type a message to start.",
                        style="dim",
                    ))
                scroll_hint = (
                    f" [dim]↑{scroll} older  ↓=newer[/dim]" if scroll > 0
                    else " [dim]↑=older[/dim]" if total > self._CHAT_WINDOW
                    else ""
                )
                avatar = rec.avatar or s.emoji(s.current_agent)
                title = (
                    f"[bold]💬 {avatar}{s.current_agent}[/bold]"
                    f"{scroll_hint} [dim cyan][echo:{s.echo_mode}][/dim cyan]"
                )
                return Panel(
                    Group(*blocks),
                    title=title,
                    border_style=border_style,
                    padding=(0, 1),
                    height=height if height is not None else self.FEED_LINES + 4,
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
        # Show the most recent FEED_LINES lines, oldest at top → newest at bottom
        visible = lines_g[-self.FEED_LINES:]
        for content, style in visible:
            text.append(content + "\n", style=style)
        for _ in range(self.FEED_LINES - len(visible)):
            text.append("\n")
        return Panel(
            text,
            title="[bold]Activity Feed[/bold]",
            border_style=border_style,
            padding=(0, 1),
            height=height if height is not None else self.FEED_LINES + 4,
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
        return Panel(
            content,
            title=f"[bold cyan]✋  {agent_id}[/bold cyan]",
            border_style="cyan",
            padding=(0, 2),
        )

    # -- Rooms + Communications panel -----------------------------------------

    def render_connections(self, height: int | None = None) -> Panel:
        """Right panel: group rooms and their members."""
        s = self._s
        text = Text()

        # ── Group rooms section ──────────────────────────────────────────────
        rooms = s.rooms  # room_name → set[agent_id]
        if rooms:
            text.append(" ─ rooms ─\n", style="bold cyan")
            for room_name, members in sorted(rooms.items()):
                is_active = s.current_agent == f"#{room_name}"
                room_style = "bold yellow" if is_active else "bold white"
                text.append(f" 💬 #{room_name}\n", style=room_style)
                for mid in sorted(members):
                    mem_em = s.emoji(mid)
                    role_tag = f" [{s.agent_roles[mid]}]" if mid in s.agent_roles else ""
                    beh = s.agent_behaviours.get(mid, "")
                    beh_tag = "  ⏰" if beh == "proactive" else ("  ⚡" if beh == "reactive" else "")
                    text.append(f"   {mem_em} {mid}{role_tag}{beh_tag}\n", style="dim")
                # last activity
                rchat = s.rooms_chat.get(room_name)
                if rchat:
                    last = list(rchat)[-1]
                    ago = _time_ago(last.ts)
                    snippet = last.content[:24].replace("\n", " ")
                    text.append(f"   ✉ {ago}  ", style="cyan")
                    text.append(f'"{snippet}"\n', style="dim")
                text.append("\n")

        if not rooms:
            text.append("  No rooms yet — use /spawn or /join to create one\n", style="dim")

        border_style = "yellow" if s.panel_focus == "connections" else "green"
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
            feed_h = max(4, panel_h - 6)   # shrink feed to fit reply below
            right_content = Group(self.render_feed(height=feed_h), reply_panel)
        else:
            right_content = self.render_feed(height=panel_h)

        # Three-column layout: sidebar | feed | connections.
        # `no_wrap=True` on the side columns prevents long agent IDs or
        # connection labels from wrapping and pushing the row taller than the
        # configured panel height (a known cause of layout corruption when
        # markdown chat replies are also present).
        layout = Table.grid(expand=True, padding=0)
        layout.add_column(width=self.SIDE_PANEL_WIDTH, no_wrap=True, overflow="ellipsis")   # sidebar
        layout.add_column(ratio=1, overflow="fold")                                          # main feed
        layout.add_column(width=self.SIDE_PANEL_WIDTH, no_wrap=True, overflow="ellipsis")   # connections
        layout.add_row(self.render_sidebar(height=panel_h), right_content, self.render_connections(height=panel_h))

        # Prompt at the bottom
        prompt_text = Text()
        prompt_text.append(prompt, style="bold green")
        prompt_text.append(input_buf + "▌")
        prompt_panel = Panel(prompt_text, border_style="dim", padding=(0, 1))

        return Group(layout, prompt_panel)
