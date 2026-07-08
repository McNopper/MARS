"""Canonical agent/scope payload builders shared by the TCP dump and REST API."""
from __future__ import annotations

from typing import Any

from mars.common.models import AgentRecord, MARSState


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
