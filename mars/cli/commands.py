"""Client-side CLI command implementations.

All ``_cmd_*`` helpers, ``_handle_bang_cmd``, and ``_expand_file_mentions``
live here so they can be imported by both ``main.py`` (re-export) and
``client.py`` (dispatch), avoiding a circular import.

None of these functions connect to the server — they operate entirely on
``MARSState`` or run local subprocesses.  Commands that need to *send* a
message to an agent receive the ``asyncio.StreamWriter`` as the ``writer``
argument and call ``writer.write(...)`` directly.

Shared helpers
--------------
- ``_send_msg(writer, target, text)``  — write one JSON msg frame
- ``_require_agent(state)``            — return current agent or set status_line
- ``_reply(state, agent, content)``    — show content in the reply panel
"""
from __future__ import annotations

import os
import re as _re
import subprocess
import tempfile
from collections import deque
from datetime import datetime
from pathlib import Path as _Path
from typing import Any

from mars.common.wire import encode_frame

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _send_msg(writer: Any, target: str, text: str) -> None:
    """Write one ``{"t": "msg", ...}`` JSON frame to *writer*."""
    writer.write(encode_frame({"t": "msg", "target": target, "text": text}))


def _require_agent(state: Any) -> str | None:
    """Return the current direct-agent target when a valid agent is selected."""
    target = getattr(state, "current_agent", None)
    if not target or target not in getattr(state, "agents", {}):
        state.status_line = "No active agent — use /spawn to start one."
        return None
    return target


def _reply(state: Any, agent: str, content: str) -> None:
    """Show *content* in the reply panel attributed to *agent*."""
    state.reply_agent   = agent
    state.reply_content = content


# ---------------------------------------------------------------------------
# @file inline expansion
# ---------------------------------------------------------------------------


def _expand_file_mentions(text: str) -> str:
    """Replace ``@path`` tokens with the file's content inline.

    Called in the message-sending path before a plain-text message is
    dispatched to the server.  Only files that exist and are readable are
    expanded; unresolvable tokens are left verbatim.
    """

    def _replace(m: _re.Match[str]) -> str:
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


def _handle_bang_cmd(line: str, state: Any | None = None) -> bool:
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
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30
        )
        output = (
            result.stdout
            + (("\n" + result.stderr) if result.stderr else "")
        ).strip()
    except subprocess.TimeoutExpired:
        output = f"[timeout after 30s: {cmd}]"
    except Exception as exc:
        output = f"[error: {exc}]"

    if state is not None:
        _reply(state, "!shell", output or "(no output)")
    else:
        print(output or "(no output)", end="\n")
    return True


# ---------------------------------------------------------------------------
# /agents  /agents available  /help  /read
# ---------------------------------------------------------------------------

_HELP_TEXT = """\
# MARS CLI — Commands

## Agents
| Command | Description |
| --- | --- |
| `/spawn <provider> [model]` | Start a new agent |
| `/stop <agent-id>` | Stop an agent |
| `/agents [available]` | List active or available agents |
| `/switch <agent>` | Switch current agent |
| `/status [agent-id]` | Show agent FSM state |
| `/verbose [agent-id]` | Toggle verbose output |
| `/avatar <emoji\\|number>` | Set your avatar |

## Conversation
| Command | Description |
| --- | --- |
| `/new` | Clear current conversation |
| `/compact` | Summarize and compact history |
| `/rewind` | Remove last message pair |
| `/ask <question>` | One-off question (not saved to history) |
| `/plan <task>` | Ask for an implementation plan |
| `/read <file>` | Read a file into the reply panel |

## Workspace
| Command | Description |
| --- | --- |
| `@file` | Inline-expand a file in your message |
| `!cmd` | Run a shell command |
| `/copy` | Copy last reply to clipboard |
| `/context` | Show token usage estimate |
| `/instructions` | Load AGENTS.md / CLAUDE.md |
| `/share [filename]` | Export session to markdown |
| `/search <query>` | Search conversation history |

## Rendering
| Command | Description |
| --- | --- |
| `/echo text\\|md\\|void` | Switch output rendering mode |

## Other
| Command | Description |
| --- | --- |
| `/version` | Show MARS version |
| `/help` | Show this help |
| `/quit` | Exit |
"""


def _cmd_help(state: Any) -> None:
    """Show the full command reference in the reply panel (``/help``)."""
    _reply(state, "📖 help", _HELP_TEXT)


def _cmd_agents(state: Any) -> None:
    """List active agents as a Markdown table in the reply panel (``/agents``)."""
    agents = getattr(state, "agents", {})
    if not agents:
        state.status_line = "No agents connected."
        return
    rows = ["| Agent ID | Type | FSM State | Active |", "| --- | --- | --- | --- |"]
    for aid, rec in agents.items():
        marker = "◀" if aid == getattr(state, "current_agent", None) else ""
        rows.append(
            f"| `{aid}` | {rec.agent_type} | {rec.fsm_state} | {marker} |"
        )
    _reply(state, "🤖 agents", "\n".join(rows))


def _cmd_agents_available(state: Any) -> None:
    """List available LLM providers and MCP services (``/agents available``)."""
    services = getattr(state, "discovered_services", [])
    if not services:
        state.status_line = "No services discovered yet — is the server connected?"
        return
    rows = [
        "| Name | Type | Status | Description |",
        "| --- | --- | --- | --- |",
    ]
    for svc in services:
        name = svc.get("name", "?")
        svc_type = svc.get("type", "service")
        if svc.get("running"):
            status = "🟢 running"
        elif svc.get("available"):
            status = "⚪ available"
        else:
            status = "🔴 unavailable"
        desc = svc.get("description", "")
        rows.append(f"| `{name}` | {svc_type} | {status} | {desc} |")
    _reply(state, "🔧 available services", "\n".join(rows))


def _cmd_read(state: Any, path: str) -> None:
    """Read a file and display its contents in the reply panel (``/read <file>``)."""
    if not path:
        state.status_line = "Usage: /read <file>"
        return
    p = _Path(path)
    if not p.exists():
        state.status_line = f"File not found: {path}"
        return
    if not p.is_file():
        state.status_line = f"Not a file: {path}"
        return
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        suffix = p.suffix.lstrip(".")
        _reply(state, f"📄 {p.name}", f"```{suffix}\n{content}\n```")
    except Exception as exc:
        state.status_line = f"Error reading {path}: {exc}"


# ---------------------------------------------------------------------------
# /copy  /new  /context  /instructions  /compact  /share  /rewind
# /search  /ask  /plan  /version
# ---------------------------------------------------------------------------


def _cmd_copy(state: Any, writer: Any) -> None:
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(content)
            state.status_line = f"📄 Saved to {f.name} (install pyperclip for clipboard)"
    else:
        state.status_line = "Nothing to copy."


def _cmd_new(state: Any) -> None:
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


def _cmd_context(state: Any) -> None:
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


def _cmd_instructions(state: Any, writer: Any) -> None:
    """Load AGENTS.md / CLAUDE.md / copilot-instructions.md and inject into system prompt."""
    if not _require_agent(state):
        return
    candidates = [
        _Path.cwd() / "AGENTS.md",
        _Path.cwd() / "CLAUDE.md",
        _Path.cwd() / ".github" / "copilot-instructions.md",
        _Path(os.path.expanduser("~")) / ".copilot" / "copilot-instructions.md",
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
    # Prepend to the wire agent's system prompt (enforced server-side)
    writer.write(encode_frame({"t": "cmd", "cmd": "set_system", "content": instructions}))
    state.status_line = (
        f"📋 Loaded instructions from: "
        f"{', '.join(p.name for p, _ in found)}"
    )


def _cmd_compact(state: Any, writer: Any) -> None:
    """Compact conversation history server-side (``/compact``).

    Asks the wire agent to generate an internal summary and replace its full
    history with [system-prompt, summary].  The summary is sent back as a
    message so the user can see what was retained.
    """
    if not _require_agent(state):
        return
    writer.write(encode_frame({"t": "cmd", "cmd": "compact"}))
    state.agents[state.current_agent].chat.clear()
    state.status_line = "📝 Compacting…"


def _cmd_share(state: Any, args: str = "") -> None:
    """Export current conversation to a markdown file (``/share [filename]``)."""
    parts = args.split(None, 1)
    filename = (
        parts[0].strip()
        if parts
        else f"mars-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    )
    target = getattr(state, "current_agent", None)
    lines = [f"# MARS Session — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
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


def _cmd_rewind(state: Any, writer: Any | None = None) -> None:
    """Remove the last user + agent message pair (``/rewind``).

    Trims the client-side display deque and, when *writer* is provided,
    sends a wire command so the server-side agent also drops the last turn.
    """
    if not _require_agent(state):
        return
    rec = state.agents[state.current_agent]
    msgs = list(rec.chat)
    removed = 0
    while msgs and removed < 2:
        msgs = msgs[:-1]
        removed += 1
    try:
        from mars.common.constants import CHAT_HISTORY_MAXLEN
        maxlen = CHAT_HISTORY_MAXLEN
    except ImportError:
        maxlen = 200
    rec.chat = deque(msgs, maxlen=maxlen)
    if writer is not None:
        writer.write(encode_frame({"t": "cmd", "cmd": "rewind"}))
    state.status_line = f"⏪ Rewound {removed} message(s)."


def _cmd_search(state: Any, query: str) -> None:
    """Search conversation history (``/search <query>``)."""
    q = query.lower()
    if not q:
        state.status_line = "Usage: /search <query>"
        return
    if not (target := _require_agent(state)):
        return
    matches = [m for m in state.agents[target].chat if q in m.content.lower()]
    if matches:
        _reply(
            state,
            target,
            "\n\n---\n\n".join(
                f"[{m.ts.strftime('%H:%M:%S')} "
                f"{'→' if m.direction == 'out' else '←'}] "
                f"{m.content[:500]}"
                for m in matches[-5:]
            ),
        )
    else:
        state.status_line = f"No matches for '{query}'"


def _cmd_ask(state: Any, writer: Any, question: str) -> None:
    """Send a one-off side question without adding it to history (``/ask <question>``).

    Uses a dedicated wire frame so the server runs the question against the
    agent's current history but does NOT append either the question or the
    reply to that history.
    """
    if not question:
        state.status_line = "Usage: /ask <question>"
        return
    if not _require_agent(state):
        return
    writer.write(encode_frame({"t": "cmd", "cmd": "ask", "text": question}))
    state.status_line = f"❓ Asked: {question[:60]}…"


def _cmd_plan(state: Any, writer: Any, task: str) -> None:
    """Ask the current agent for an implementation plan (``/plan <task>``)."""
    if not task:
        state.status_line = "Usage: /plan <task description>"
        return
    if not (target := _require_agent(state)):
        return
    _send_msg(
        writer, target,
        "Please create a detailed implementation plan for the following "
        "task. Break it into numbered steps, identify potential risks, "
        "and list what you'll need before starting. "
        "Do NOT start implementing yet.\n\nTask: " + task,
    )


def _cmd_version(state: Any) -> None:
    """Show the installed MARS version (``/version``)."""
    v = "unknown"
    # Try importlib first (works when installed as a package)
    try:
        from importlib.metadata import version as _ver
        v = _ver("mars")
    except Exception:
        pass
    # Fall back to reading pyproject.toml from repo root
    if v == "unknown":
        try:
            import tomllib  # Python 3.11+
            pyproject = _Path(__file__).parents[2] / "pyproject.toml"
            if pyproject.exists():
                data = tomllib.loads(pyproject.read_text("utf-8"))
                v = data.get("project", {}).get("version", "unknown")
        except Exception:
            pass
    state.status_line = f"MARS v{v}"


