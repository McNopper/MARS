"""Server→client event application: mutate a local MARSState from wire events."""
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime

from mars.common.models import (
    AgentRecord,
    ChatMessage,
    FeedItem,
    MARSState,
)
from mars.cli.nav import _is_conversational, _sync_sidebar_cursor
from mars.cli.utils import _normalize_agent_type


def _agent_id_to_service(agent_id: str) -> str | None:
    """Extract the service name from an agent_id.

    ``llm.ollama.qwen3:4b@1``  → ``"ollama"``
    ``svc.filesystem@1``        → ``"filesystem"``
    ``a2a.federation@1``        → ``"federation"``
    """
    parts = agent_id.split(".")
    if len(parts) >= 2:
        return parts[1].split("@")[0]
    return None


def _update_service_running(state: MARSState, agent_id: str, *, running: bool) -> None:
    """Flip the ``running`` flag on the matching entry in ``state.discovered_services``."""
    svc_name = _agent_id_to_service(agent_id)
    if not svc_name:
        return
    for svc in state.discovered_services:
        if svc.get("name") == svc_name:
            svc["running"] = running
            break


def apply_event(state: MARSState, ev: dict, *, tty: bool = True) -> None:
    """Apply one server event to the local MARSState copy."""
    t = ev.get("t", "")

    if t == "state":
        state.platform_name = ev.get("platform_name", "mars")
        state.agents.clear()
        state.agent_roles.clear()
        state.agent_behaviours.clear()
        for aid, data in ev.get("agents", {}).items():
            state.agents[aid] = AgentRecord(
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
                state.agent_roles[aid] = role
            else:
                state.agent_roles.pop(aid, None)
            if behaviour:
                state.agent_behaviours[aid] = behaviour
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
        state.feed = deque(feed_items, maxlen=30)
        # Restore per-agent chat history
        for aid, msgs in ev.get("chats", {}).items():
            rec = state.agents.get(aid)
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
        state.current_agent = current.lstrip("#") if isinstance(current, str) else None
        if state.current_agent:
            state.chat_scroll = 0
        bare = state.current_agent or ""
        if bare and bare in state.agents:
            state.agents[bare].is_current = True
        elif not state.current_agent:
            agents = [
                a for a in state.agents
                if a != state.my_agent_id and _is_conversational(state.agents[a])
            ]
            if agents:
                state.current_agent = agents[0]
                state.agents[agents[0]].is_current = True
        _sync_sidebar_cursor(state)
        # Store the service registry delivered alongside the state frame.
        state.discovered_services = ev.get("services", [])

    elif t == "spawn":
        aid = ev.get("agent_id", "")
        if aid:
            state.agents[aid] = AgentRecord(
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
                state.agent_roles[aid] = role
            if behaviour:
                state.agent_behaviours[aid] = behaviour
            # Auto-select first conversational agent (LLM etc.) as current chat target.
            rec = state.agents.get(aid)
            if (not state.current_agent
                    and aid != state.my_agent_id
                    and rec is not None
                    and _is_conversational(rec)
                    and rec.agent_type not in ("HumanUser",)):
                state.current_agent = aid
                rec.is_current = True
                _sync_sidebar_cursor(state)
            # Mark the corresponding service as running in the services panel
            _update_service_running(state, aid, running=True)

    elif t == "despawn":
        aid = ev.get("agent_id", "")
        state.agents.pop(aid, None)
        state.agent_roles.pop(aid, None)
        state.agent_behaviours.pop(aid, None)
        if state.current_agent == aid:
            remaining = [a for a in state.agents if a != state.my_agent_id]
            state.current_agent = remaining[0] if remaining else None
        # Unmark the service as running only if no other agent of that type remains
        svc_name = _agent_id_to_service(aid)
        if svc_name:
            still_running = any(
                _agent_id_to_service(a) == svc_name
                for a in state.agents
            )
            if not still_running:
                _update_service_running(state, aid, running=False)

    elif t == "welcome":
        new_id = ev.get("your_id", "cli-user@1")
        state.my_agent_id = new_id
        # Register ourselves so we appear in the sidebar as the "You" entry
        if new_id not in state.agents:
            state.agents[new_id] = AgentRecord(
                agent_id=new_id,
                agent_type="HumanUser",
                domain="cli",
                platform="local",
                skills=[],
            )
        # Clear current_agent if it somehow points to our own ID
        if state.current_agent == new_id:
            state.current_agent = None

    elif t == "feed":
        try:
            ts = datetime.fromisoformat(ev["ts"])
        except Exception:
            ts = datetime.now()
        state.feed.append(FeedItem(
            ts=ts,
            event_type=ev.get("event_type", "message"),
            from_id=ev.get("from_id", ""),
            to_id=ev.get("to_id", ""),
            snippet=ev.get("snippet", ""),
            performative=ev.get("performative", "INFORM"),
        ))

    elif t == "chat":
        aid = ev.get("agent_id", "")
        rec = state.agents.get(aid)
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
        rec = state.agents.get(aid)
        if rec:
            rec.fsm_state    = ev.get("fsm_state", rec.fsm_state)
            rec.fsm_strategy = ev.get("fsm_strategy", rec.fsm_strategy)
            rec.fsm_loop     = ev.get("fsm_loop")

    elif t == "status":
        state.status_line  = ev.get("text", "")
        state.status_style = ev.get("style", "")

    elif t == "artifact":
        name = ev.get("name", "artifact")
        size = ev.get("size", "?")
        created_by = ev.get("created_by", "server")
        mime = ev.get("mime", "")
        state.status_line = f"Artifact received: {name} ({size} bytes)"
        state.status_style = "bold blue"
        # Note: no global feed entry — artifact events are scoped to the
        # creator agent's chat (inline image preview below) so they don't
        # appear in unrelated chats.
        # Inline-preview images in the creator agent's chat pane
        preview_b64 = ev.get("preview_data")
        preview_mime = ev.get("preview_mime", mime)
        if preview_b64 and isinstance(preview_b64, str) and str(preview_mime).startswith("image/"):
            try:
                img_bytes = base64.b64decode(preview_b64)
            except Exception:
                img_bytes = None
            if img_bytes:
                rec = state.agents.get(created_by)
                if rec is None and created_by in ("server",):
                    rec = state.agents.get(state.current_agent or "")
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
                rec = state.agents.get(name)
                if rec is None:
                    state.agents[name] = AgentRecord(
                        agent_id=name,
                        agent_type="Provider",
                        domain="services",
                        platform="remote",
                        skills=list(ev.get("skills", [])),
                    )
                else:
                    rec.agent_type = "Provider"
                    rec.domain = "services"
                    rec.platform = "remote"
                    rec.skills = list(ev.get("skills", rec.skills))
            else:
                state.agents.pop(name, None)
        icon = "🔌" if t == "client_connect" else "⛔"
        verb = "connected" if t == "client_connect" else "disconnected"
        peer = f"{name} @ {ev.get('addr', '?')}" if name else ev.get("addr", "?")
        state.feed.append(FeedItem(
            ts=datetime.now(), event_type="fed",
            from_id="server", to_id="",
            snippet=f"{icon} Client {verb}: {peer}",
        ))

    elif t == "switch":
        new_target = ev.get("current_agent")
        if new_target is not None:
            for rec in state.agents.values():
                rec.is_current = False
            state.current_agent = new_target.lstrip("#")
            state.chat_scroll = 0
            bare = state.current_agent
            if bare in state.agents:
                state.agents[bare].is_current = True
            _sync_sidebar_cursor(state)
