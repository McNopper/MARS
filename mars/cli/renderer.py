from __future__ import annotations

import io
import time
from typing import Any

from mars.common.models import (
    EVENT_ICONS,
    VENDOR_EMOJIS,
    ChatMessage,
    MARSState,
)
from mars.cli.nav import _is_conversational, _mcp_agent_ids

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
    from PIL import Image as _PILImage
    _PIL_OK = True
except ImportError:
    _PIL_OK = False
    _PILImage = None  # type: ignore[assignment]

try:
    from mars.cli.math_renderer import preprocess_math as _preprocess_math
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

    def render_services(self, height: int | None = None) -> Panel:
        """Left panel: Unified Services panel.

        Reads from ``state.discovered_services`` which is populated from the
        standard ``state`` wire frame the server sends on connect — the same
        data any agent receives via DiscoveryService.  No direct registry import.
        """
        s = self._s
        text = Text()
        is_focused = s.panel_focus == "services"
        max_rows = max(1, (height - 2) if height else 999)

        if height is not None:
            s.services_visible_height = max(1, height - 2)

        services = s.discovered_services
        if not services:
            text.append("  [dim]No services available[/dim]\n")
            return Panel(
                text,
                title="[bold cyan]🔧 Services[/bold cyan]",
                border_style="green" if is_focused else "blue",
                padding=(0, 0),
                height=height,
            )

        type_emojis = {"llm": "🤖", "service": "⚙️"}
        by_type: dict[str, list[dict]] = {"llm": [], "service": []}
        for svc in services:
            raw = svc.get("type", "service")
            # Normalise legacy type names from older server versions
            bucket = raw if raw in by_type else "service"
            by_type[bucket].append(svc)

        # Build flat row list for cursor/scroll
        rows: list[tuple[str, str | None]] = []  # (type_key, svc_name_or_None)
        for svc_type in ("llm", "service"):
            if not by_type.get(svc_type):
                continue
            rows.append((svc_type, None))
            for svc in by_type[svc_type]:
                rows.append((svc_type, svc["name"]))

        total_rows = len(rows)
        s.services_cursor = max(0, min(s.services_cursor, total_rows - 1))
        s.services_scroll = max(0, min(s.services_scroll, total_rows - 1))

        rows_used = 0
        for i, (svc_type, svc_name) in enumerate(rows):
            if i < s.services_scroll:
                continue
            if rows_used >= max_rows:
                break
            is_selected = is_focused and (i == s.services_cursor)
            cursor_ch = "►" if is_selected else " "
            style = "bold cyan" if is_selected else ""
            if svc_name is None:
                emoji = type_emojis.get(svc_type, "📦")
                count = len(by_type[svc_type])
                label = "LLM Agents" if svc_type == "llm" else "MCP Services"
                text.append(f"{cursor_ch} {emoji} ", style=style)
                text.append(label, style="bold white" if is_selected else "white")
                text.append(f" ({count})\n", style="dim")
            else:
                svc_data = next(
                    (s2 for s2 in by_type[svc_type] if s2["name"] == svc_name), {}
                )
                if svc_data.get("running"):
                    dot_style = "green"
                elif svc_data.get("available"):
                    dot_style = "white"
                else:
                    dot_style = "red"
                text.append(f"{cursor_ch} ", style=style)
                text.append("● ", style=dot_style)
                text.append(f"{svc_name}\n", style="white" if is_selected else "dim")
            rows_used += 1

        total_svcs = len(services)
        subtitle = f"[dim]{total_svcs} service{'s' if total_svcs != 1 else ''}"
        if s.services_scroll > 0:
            subtitle += f" ↑{s.services_scroll}"
        subtitle += "[/dim]"
        return Panel(
            text,
            title="[bold cyan]🔧 Services[/bold cyan]",
            subtitle=subtitle,
            border_style="green" if is_focused else "blue",
            padding=(0, 0),
            height=height,
        )

    _PANEL_FOCUS_ORDER = ("services", "chat", "connections")  # Tab cycle order

    def render_sidebar(self, height: int | None = None) -> Panel:
        """Left panel: Agent providers sidebar (DEPRECATED - use render_services for unified Services panel)."""
        s = self._s
        text = Text()

        # Three-level hierarchy:
        # Level 1: MARS server instance (local, or A2A-connected servers)
        # Level 2: Provider names (Ollama, Anthropic, etc.)
        # Level 3: Available models (unique models, not instances)

        # Group by server_addr, then by provider, then collect unique models
        servers: dict[str, dict[str, set[str]]] = {}
        for aid, rec in s.agents.items():
            server = rec.server_addr or "local"
            if server not in servers:
                servers[server] = {}
            provider = rec.vendor or "unknown"
            if provider not in servers[server]:
                servers[server][provider] = set()
            if rec.model:
                servers[server][provider].add(rec.model)

        max_rows = max(1, (height - 2) if height else 999)

        # Track visible height for scroll-follow
        if height is not None:
            s.sidebar_visible_height = max(1, height - 2)

        # Calculate total rows for cursor clamping
        total_rows = 0
        for server, providers in sorted(servers.items()):
            total_rows += 1  # server header
            for provider in sorted(providers.keys()):
                total_rows += 1  # provider header
                total_rows += len(providers[provider])  # models

        # Clamp cursor
        if total_rows > 0:
            s.sidebar_cursor = max(0, min(s.sidebar_cursor, total_rows - 1))
            s.sidebar_scroll = max(0, min(s.sidebar_scroll, total_rows - 1))
        else:
            s.sidebar_cursor = 0
            s.sidebar_scroll = 0

        is_focused = s.panel_focus == "sidebar"

        rows_used = 0
        current_row = 0

        for server, providers in sorted(servers.items()):
            if current_row < s.sidebar_scroll:
                current_row += 1
                for provider in sorted(providers.keys()):
                    current_row += 1
                    current_row += len(providers[provider])
                continue

            if rows_used >= max_rows:
                break

            is_server_selected = is_focused and (current_row == s.sidebar_cursor)

            # Server header row (Level 1)
            cursor_ch = "►" if is_server_selected else " "

            server_emoji = "🏠" if server == "local" else "🌐"
            text.append(cursor_ch, style="bold cyan" if is_server_selected else "")
            text.append(f" {server_emoji} ", style="")
            text.append(f"{server}", style="bold white" if is_server_selected else "white")
            total_models = sum(len(models) for models in providers.values())
            text.append(f" ({total_models} model{'s' if total_models != 1 else ''})", style="dim")
            text.append("\n")
            rows_used += 1
            current_row += 1

            # Providers under server (Level 2)
            for provider in sorted(providers.keys()):
                if rows_used >= max_rows:
                    break

                if current_row < s.sidebar_scroll:
                    current_row += 1
                    current_row += len(providers[provider])
                    continue

                is_provider_selected = is_focused and (current_row == s.sidebar_cursor)

                cursor_ch = "►" if is_provider_selected else " "

                vendor_emoji = VENDOR_EMOJIS.get(provider, "📦")
                text.append(cursor_ch, style="bold cyan" if is_provider_selected else "")
                text.append(f" {vendor_emoji} ", style="")
                text.append(f"{provider.capitalize()}", style="bold white" if is_provider_selected else "white")
                text.append(f" ({len(providers[provider])} model{'s' if len(providers[provider]) != 1 else ''})", style="dim")
                text.append("\n")
                rows_used += 1
                current_row += 1

                # Models under provider (Level 3)
                for model in sorted(providers[provider]):
                    if rows_used >= max_rows:
                        break
                    if current_row < s.sidebar_scroll:
                        current_row += 1
                        continue

                    is_model_selected = is_focused and (current_row == s.sidebar_cursor)

                    cursor_ch = "►" if is_model_selected else " "
                    model_short = model.split('/')[-1][:20]

                    text.append(cursor_ch, style="bold cyan" if is_model_selected else "")
                    text.append(" 🧠 ", style="")
                    text.append(model_short, style="white")
                    text.append("\n")

                    rows_used += 1
                    current_row += 1

        if not text.plain:
            text.append("  [dim]No models yet — /spawn to start[/dim]\n")

        total_models = sum(len(models) for providers in servers.values() for models in providers.values())
        server_count = len(servers)
        subtitle = f"[dim]{server_count} server{'s' if server_count != 1 else ''} · {total_models} model{'s' if total_models != 1 else ''}"
        if s.sidebar_scroll > 0:
            subtitle += f" ↓{s.sidebar_scroll}"
        subtitle += "[/dim]"

        border_style = "green" if is_focused else "blue"
        return Panel(
            text,
            title="[bold cyan]🤖 Agent Providers[/bold cyan]",
            subtitle=subtitle,
            border_style=border_style,
            padding=(0, 0),
            height=height,
        )

    def render_mcp_panel(self, height: int | None = None) -> Panel:
        """Tool Providers panel (DEPRECATED - use render_services for unified Services panel)."""
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
            title="[bold magenta]🔧 Tool Providers[/bold magenta]",
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
    # NOTE: _PANEL_FOCUS_ORDER is defined earlier in the class (near render_services)

    @staticmethod
    def _image_to_halfblocks(data: bytes, max_width: int = 60) -> Text | None:
        """Render an image to Unicode half-block characters.

        Each output line shows two image rows: the top pixel becomes the
        character foreground (▀) and the bottom pixel becomes the background.
        Works in any terminal that supports 24-bit colour (most modern ones,
        including Windows Terminal).
        """
        if not _PIL_OK:
            return None
        try:
            img = _PILImage.open(io.BytesIO(data)).convert("RGB")
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
        msgs: list[ChatMessage],
        scroll: int,
        agent_emoji: str = "",
        window: int | None = None,
    ) -> tuple[list[Any], int]:
        """Return (blocks, total) for a chat message list.

        Each message is attributed to its actual sender (``cm.sender``) with a
        per-sender emoji, so rendering is identical for every conversation.
        """
        s = self._s
        w = window if window is not None else self._CHAT_WINDOW_MIN
        total = len(msgs)
        end = max(0, total - scroll)
        start = max(0, end - w)
        recent = msgs[start:end]
        blocks: list[Any] = []
        for cm in recent:
            ts = cm.ts.strftime("%H:%M:%S")
            if cm.direction == "system":
                blocks.append(Text(f"  {cm.content}", style="dim italic"))
                blocks.append(Text(""))
                continue
            if cm.direction == "out":
                sender_em = s.emoji(cm.sender)
                header = Text(f"{sender_em} {cm.sender}  {ts}", style="bold green")
                body = Text(cm.content, style="white", overflow="fold", no_wrap=False)
            else:
                if s.echo_mode == "void":
                    continue
                # Always attribute by actual sender
                sender_em = s.emoji(cm.sender)
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

        # --- Unified 1:1 agent chat (conversational and non-conversational) ---
        if s.current_agent and s.current_agent in s.agents and s.current_agent != s.my_agent_id:
            rec = s.agents[s.current_agent]
            agent_msgs = list(rec.chat)
            total = len(agent_msgs)
            max_scroll = max(0, total - window)
            scroll = max(0, min(s.chat_scroll, max_scroll))
            blocks, total = self._render_chat_blocks(agent_msgs, scroll, window=window)
            if not blocks:
                blocks.append(Text(
                    f"Direct chat with {s.current_agent} — type a message to start.",
                    style="dim",
                ))
            scroll_hint = (
                f" [dim]↑{scroll} older  ↓=newer[/dim]" if scroll > 0
                else " [dim]↑=older[/dim]" if total > window
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

    def print_header(self, console: Console) -> None:
        console.print(self.render_feed())
        console.print(self.render_services())
        console.print(Rule(style="dim"))

    # -- Reply panel (raised-hand acknowledgement) ---------------------------

    def render_reply_panel(self) -> Panel | None:
        agent_id = self._s.reply_agent
        content  = self._s.reply_content
        if not agent_id or not content:
            return None
        renderable: Any = (
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
        """Right panel: hierarchical view of conversations (agent → conversation partners)."""
        s = self._s
        text = Text()
        _spin = self._THINKING_SPINNER[int(time.monotonic() * 8) % len(self._THINKING_SPINNER)]

        # Build conversation hierarchy: user agent → agents they can chat with
        # For now, show the user's agent with all conversational agents as children
        conversations: dict[str, list[str]] = {}

        # Get all conversational agents (excluding user)
        conv_agents = []
        for aid, rec in s.agents.items():
            if aid != s.my_agent_id and _is_conversational(rec):
                conv_agents.append(aid)

        # User agent shows all conversational agents as potential chat partners
        if s.my_agent_id in s.agents:
            conversations[s.my_agent_id] = sorted(conv_agents)

        if not conversations:
            text.append("  [dim]No conversations yet[/dim]\n")
            border_style = "green" if s.panel_focus == "connections" else "blue"
            return Panel(
                text,
                title="[bold green]💬 Communications[/bold green]",
                border_style=border_style,
                padding=(0, 0),
                height=height,
            )

        sorted_conversations = sorted(conversations.items())
        if height is not None:
            s.connections_visible_height = max(1, height - 2)
        visible_rows = max(1, s.connections_visible_height)

        # Calculate total rows for cursor clamping
        total_rows = 0
        for agent, partners in sorted_conversations:
            total_rows += 1  # agent header
            total_rows += len(partners)  # partners

        # Clamp cursor and scroll
        if total_rows > 0:
            s.connections_cursor = max(0, min(s.connections_cursor, total_rows - 1))
            s.connections_scroll = max(0, min(s.connections_scroll, total_rows - 1))

        is_focused = s.panel_focus == "connections"
        rows_used = 0
        current_row = 0

        for agent, partners in sorted_conversations:
            if current_row < s.connections_scroll:
                current_row += 1
                current_row += len(partners)
                continue

            if rows_used >= visible_rows:
                break

            is_agent_selected = is_focused and (current_row == s.connections_cursor)
            is_active_source = s.current_agent and (
                (s.current_agent == agent) or
                (any(p == s.current_agent for p in partners))
            )

            # Agent header row
            if is_agent_selected:
                arrow = "►"
                agent_style = "bold yellow"
            elif is_active_source:
                arrow = "›"
                agent_style = "bold white"
            else:
                arrow = " "
                agent_style = "white"

            agent_rec = s.agents.get(agent)
            if agent_rec:
                is_err = agent_rec.fsm_state in ("ERROR", "CRASHED", "FAILED", "BLOCKED")
                is_thinking = agent_rec.fsm_state == "THINKING"
                if is_err:
                    dot = ("●", "red")
                elif is_thinking:
                    dot = (_spin, "bold blue")
                else:
                    dot = ("●", "green")
            else:
                dot = ("●", "green")

            agent_emoji = s.emoji(agent)
            text.append(f"{arrow} ", style=agent_style)
            text.append(dot[0], style=dot[1])
            text.append(f" {agent_emoji} {agent}\n", style=agent_style)
            rows_used += 1
            current_row += 1

            # Conversation partners (children)
            for partner in partners:
                if rows_used >= visible_rows:
                    break
                if current_row < s.connections_scroll:
                    current_row += 1
                    continue

                is_partner_selected = is_focused and (current_row == s.connections_cursor)
                is_active_target = (s.current_agent == partner)

                if is_partner_selected or is_active_target:
                    child_arrow = "►"
                    partner_style = "bold yellow" if is_partner_selected else "bold white"
                else:
                    child_arrow = " "
                    partner_style = "dim"

                partner_rec = s.agents.get(partner)
                if partner_rec:
                    partner_is_err = partner_rec.fsm_state in ("ERROR", "CRASHED", "FAILED", "BLOCKED")
                    partner_is_thinking = partner_rec.fsm_state == "THINKING"
                    if partner_is_err:
                        partner_dot = ("●", "red")
                    elif partner_is_thinking:
                        partner_dot = (_spin, "bold blue")
                    else:
                        partner_dot = ("●", "green")
                else:
                    partner_dot = ("●", "green")

                partner_emoji = s.emoji(partner)
                text.append(f"   {child_arrow} ", style=partner_style)
                text.append(partner_dot[0], style=partner_dot[1])
                text.append(f" {partner_emoji} {partner}\n", style=partner_style)

                rows_used += 1
                current_row += 1

        border_style = "green" if is_focused else "blue"
        return Panel(
            text,
            title="[bold green]💬 Communications[/bold green]",
            border_style=border_style,
            padding=(0, 0),
            height=height,
        )

    # -- Live renderable (used by rich.live.Live) ----------------------------

    def render_group(self, input_buf: str = "", prompt: str = "> ",
                     console_height: int = 40) -> Group:
        # Available height for panels: total minus prompt panel (3 lines)
        panel_h = max(4, console_height - 3)

        # Right-side content: feed fills the available height
        reply_panel = self.render_reply_panel()
        if reply_panel:
            feed_h = max(4, panel_h - self._REPLY_PANEL_H)
            right_content = Group(self.render_feed(height=feed_h), reply_panel)
        else:
            right_content = self.render_feed(height=panel_h)

        # Left column: Services panel (full height).
        left_content = self.render_services(height=panel_h)

        # Right-side column: Communications panel (full height).
        right_column = self.render_connections(height=panel_h)

        # Three-column layout: [services] | feed | [communications].
        # `no_wrap=True` on the side columns prevents long service IDs or
        # connection labels from wrapping and pushing the row taller than the
        # configured panel height (a known cause of layout corruption when
        # markdown chat replies are also present).
        layout = Table.grid(expand=True, padding=0)
        layout.add_column(width=self.SIDE_PANEL_WIDTH, no_wrap=True, overflow="ellipsis")   # left (services)
        layout.add_column(ratio=1, overflow="fold")                                          # main feed
        layout.add_column(width=self.SIDE_PANEL_WIDTH, no_wrap=True, overflow="ellipsis")   # right (communications)
        layout.add_row(left_content, right_content, right_column)

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
