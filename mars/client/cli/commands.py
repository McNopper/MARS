"""Client-side CLI command implementations.

All ``_cmd_*`` helpers, ``_handle_bang_cmd``, and ``_expand_file_mentions``
live here so they can be imported by both ``main.py`` (re-export) and
``client.py`` (dispatch), avoiding a circular import.

None of these functions connect to the server — they operate entirely on
``MARSState`` or run local subprocesses.  Commands that need to *send* a
message to an agent receive the ``asyncio.StreamWriter`` as the ``writer``
argument and call ``writer.write(...)`` directly.
"""
from __future__ import annotations

import json
import re as _re
from pathlib import Path as _Path
from typing import Any


# ---------------------------------------------------------------------------
# @file inline expansion
# ---------------------------------------------------------------------------


def _expand_file_mentions(text: str) -> str:
    """Replace ``@path`` tokens with the file's content inline.

    Called in the message-sending path before a plain-text message is
    dispatched to the server.  Only files that exist and are readable are
    expanded; unresolvable tokens are left verbatim.
    """

    def _replace(m: "_re.Match[str]") -> str:
        path = _Path(m.group(1))
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                suffix = path.suffix.lstrip(".")
                return f"\n```{suffix}\n# {path}\n{content}\n```\n"
            except Exception:
                return m.group(0)
        return m.group(0)

    return _re.sub(r"@(\S+)", _replace, text)


# ---------------------------------------------------------------------------
# !cmd shell shortcut
# ---------------------------------------------------------------------------


def _handle_bang_cmd(line: str, state: "Any | None" = None) -> bool:
    """Handle ``!<shell-command>`` shortcut; returns True if handled.

    In TUI mode pass *state* so that output is routed to the reply panel
    instead of being printed directly to stdout (which would corrupt the Live
    display).  In pipe / non-TUI mode omit *state* and output goes to stdout.
    """
    if not line.startswith("!"):
        return False
    cmd = line[1:].strip()
    if not cmd:
        return True
    import subprocess as _sp
    try:
        result = _sp.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = (
            result.stdout
            + (("\n" + result.stderr) if result.stderr else "")
        ).strip()
    except _sp.TimeoutExpired:
        output = f"[timeout after 30s: {cmd}]"
    except Exception as exc:
        output = f"[error: {exc}]"

    if state is not None:
        state.reply_agent = "!shell"
        state.reply_content = output or "(no output)"
    else:
        print(output or "(no output)", end="\n")
    return True


# ---------------------------------------------------------------------------
# /copy  /new  /context  /instructions  /compact  /share  /rewind
# /search  /ask  /plan  /version  /theme
# ---------------------------------------------------------------------------


def _cmd_copy(state: "Any", writer: "Any") -> None:
    """Copy the last agent reply to the clipboard (``/copy``)."""
    content = getattr(state, "reply_content", "") or ""
    if not content:
        agent = getattr(state, "current_agent", None)
        if agent and agent in getattr(state, "agents", {}):
            rec = state.agents[agent]
            msgs = list(rec.chat)
            inbound = [m for m in msgs if m.direction == "in"]
            if inbound:
                content = inbound[-1].content
    if content:
        try:
            import pyperclip  # type: ignore[import]
            pyperclip.copy(content)
            state.status_line = "✅ Copied to clipboard."
        except ImportError:
            import tempfile as _tempfile
            import os as _os
            with _tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False
            ) as f:
                f.write(content)
            state.status_line = (
                f"📄 Saved to {f.name} (install pyperclip for clipboard)"
            )
    else:
        state.status_line = "Nothing to copy."


def _cmd_new(state: "Any") -> None:
    """Clear conversation history for the current agent (``/new``)."""
    agent = getattr(state, "current_agent", None)
    if agent and agent in getattr(state, "agents", {}):
        state.agents[agent].chat.clear()
    feed = getattr(state, "feed", None)
    if feed is not None:
        feed.clear()
    state.reply_agent = ""
    state.reply_content = ""
    state.status_line = "🆕 Conversation cleared."


def _cmd_context(state: "Any") -> None:
    """Show token usage estimate for the current context (``/context``)."""
    agent = getattr(state, "current_agent", None)
    total_chars = 0
    msg_count = 0
    if agent and agent in getattr(state, "agents", {}):
        rec = state.agents[agent]
        for m in rec.chat:
            total_chars += len(m.content)
            msg_count += 1
    est_tokens = total_chars // 4
    state.status_line = (
        f"📊 Context: ~{est_tokens:,} tokens across {msg_count} messages "
        f"({total_chars:,} chars)"
    )


def _cmd_instructions(state: "Any", writer: "Any") -> None:
    """Load AGENTS.md / CLAUDE.md / copilot-instructions.md and send to current agent (``/instructions``)."""
    import os as _os
    candidates = [
        _Path.cwd() / "AGENTS.md",
        _Path.cwd() / "CLAUDE.md",
        _Path.cwd() / ".github" / "copilot-instructions.md",
        _Path(_os.path.expanduser("~")) / ".copilot" / "copilot-instructions.md",
    ]
    found = [(p, p.read_text("utf-8")) for p in candidates if p.exists()]
    if not found:
        state.status_line = (
            "No instruction files found "
            "(AGENTS.md, CLAUDE.md, .github/copilot-instructions.md)"
        )
        return
    instructions = "\n\n".join(
        f"# From {p.name}\n{content}" for p, content in found
    )
    target = getattr(state, "current_agent", None)
    if target:
        writer.write(
            (
                json.dumps(
                    {
                        "t": "msg",
                        "target": target,
                        "text": f"[SYSTEM INSTRUCTIONS]\n{instructions}",
                    }
                )
                + "\n"
            ).encode()
        )
        state.status_line = (
            f"📋 Loaded instructions from: "
            f"{', '.join(p.name for p, _ in found)}"
        )
    else:
        state.status_line = "No active agent to send instructions to."


def _cmd_compact(state: "Any", writer: "Any") -> None:
    """Summarize and compact conversation history (``/compact``)."""
    target = getattr(state, "current_agent", None)
    if not target or target not in getattr(state, "agents", {}):
        state.status_line = "No active agent."
        return
    rec = state.agents[target]
    history = "\n".join(
        f"{'User' if m.direction == 'out' else 'Agent'}: {m.content[:200]}"
        for m in list(rec.chat)[-20:]
    )
    prompt = (
        "Please summarize the following conversation in 2-3 paragraphs, "
        "keeping all important facts, decisions, and context:\n\n"
        + history
    )
    writer.write(
        (json.dumps({"t": "msg", "target": target, "text": prompt}) + "\n").encode()
    )
    rec.chat.clear()
    state.status_line = "📝 Compacting... reply will replace history."


def _cmd_share(state: "Any", args: str = "") -> None:
    """Export current conversation to a markdown file (``/share [filename]``)."""
    from datetime import datetime as _dt
    parts = args.split(None, 1)
    filename = (
        parts[0].strip()
        if parts
        else f"mars-session-{_dt.now().strftime('%Y%m%d-%H%M%S')}.md"
    )
    target = getattr(state, "current_agent", None)
    lines = [f"# MARS Session — {_dt.now().strftime('%Y-%m-%d %H:%M')}\n"]
    if target and target in getattr(state, "agents", {}):
        for m in state.agents[target].chat:
            speaker = (
                "**You**" if m.direction == "out" else f"**{target}**"
            )
            lines.append(
                f"{speaker} _{m.ts.strftime('%H:%M:%S')}_\n\n{m.content}\n\n---\n"
            )
    _Path(filename).write_text("\n".join(lines), encoding="utf-8")
    state.status_line = f"📤 Session exported to {filename}"


def _cmd_rewind(state: "Any") -> None:
    """Remove the last user + agent message pair (``/rewind``)."""
    from collections import deque as _deque
    target = getattr(state, "current_agent", None)
    if not target or target not in getattr(state, "agents", {}):
        state.status_line = "Nothing to rewind."
        return
    rec = state.agents[target]
    msgs = list(rec.chat)
    removed = 0
    while msgs and removed < 2:
        msgs = msgs[:-1]
        removed += 1
    try:
        from mars.constants import CHAT_HISTORY_MAXLEN
        maxlen = CHAT_HISTORY_MAXLEN
    except ImportError:
        maxlen = 200
    rec.chat = _deque(msgs, maxlen=maxlen)
    state.status_line = f"⏪ Rewound {removed} message(s)."


def _cmd_search(state: "Any", query: str) -> None:
    """Search conversation history (``/search <query>``)."""
    q = query.lower()
    target = getattr(state, "current_agent", None)
    if not q:
        state.status_line = "Usage: /search <query>"
        return
    if target and target in getattr(state, "agents", {}):
        matches = [
            m
            for m in state.agents[target].chat
            if q in m.content.lower()
        ]
        if matches:
            state.reply_agent = target
            state.reply_content = "\n\n---\n\n".join(
                f"[{m.ts.strftime('%H:%M:%S')} "
                f"{'→' if m.direction == 'out' else '←'}] "
                f"{m.content[:500]}"
                for m in matches[-5:]
            )
        else:
            state.status_line = f"No matches for '{query}'"
    else:
        state.status_line = "No active agent."


def _cmd_ask(state: "Any", writer: "Any", question: str) -> None:
    """Send a one-off side question without polluting history (``/ask <question>``)."""
    if not question:
        state.status_line = "Usage: /ask <question>"
        return
    target = getattr(state, "current_agent", None)
    if target:
        writer.write(
            (
                json.dumps(
                    {
                        "t": "msg",
                        "target": target,
                        "text": (
                            "[ONE-OFF QUESTION — do not add to your "
                            f"conversation history]\n{question}"
                        ),
                    }
                )
                + "\n"
            ).encode()
        )
        state.status_line = f"❓ Asked: {question[:60]}…"
    else:
        state.status_line = "No active agent."


def _cmd_plan(state: "Any", writer: "Any", task: str) -> None:
    """Ask the current agent for an implementation plan (``/plan <task>``)."""
    if not task:
        state.status_line = "Usage: /plan <task description>"
        return
    target = getattr(state, "current_agent", None)
    if target:
        prompt = (
            "Please create a detailed implementation plan for the following "
            "task. Break it into numbered steps, identify potential risks, "
            "and list what you'll need before starting. "
            "Do NOT start implementing yet.\n\nTask: " + task
        )
        writer.write(
            (json.dumps({"t": "msg", "target": target, "text": prompt}) + "\n").encode()
        )
    else:
        state.status_line = "No active agent."


def _cmd_version(state: "Any") -> None:
    """Show the installed MARS version (``/version``)."""
    try:
        from importlib.metadata import version as _ver
        v = _ver("mars")
    except Exception:
        v = "unknown"
    state.status_line = f"MARS v{v}"


_THEMES: "dict[str, dict[str, str]]" = {
    "dark":      {"primary": "cyan",   "secondary": "blue",  "accent": "green"},
    "light":     {"primary": "blue",   "secondary": "green", "accent": "cyan"},
    "dracula":   {"primary": "purple", "secondary": "pink",  "accent": "yellow"},
    "solarized": {"primary": "yellow", "secondary": "green", "accent": "cyan"},
}


def _cmd_theme(state: "Any", theme: str) -> None:
    """Switch color theme (``/theme [name]``)."""
    if not theme:
        current = getattr(state, "theme", "dark")
        available = ", ".join(_THEMES.keys())
        state.status_line = f"Current theme: {current}. Available: {available}"
        return
    if theme in _THEMES:
        state.theme = theme
        state.status_line = f"🎨 Theme set to '{theme}'"
    else:
        state.status_line = (
            f"Unknown theme '{theme}'. "
            f"Available: {', '.join(_THEMES.keys())}"
        )
