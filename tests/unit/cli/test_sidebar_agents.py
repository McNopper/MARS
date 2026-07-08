"""Unit tests for sidebar agent basics."""
from __future__ import annotations

import pytest

from mars.cli.main import AgentRecord, MARSRenderer, MARSState, _local_ip


class TestLocalIp:
    def test_returns_string(self):
        ip = _local_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0

    def test_not_bind_all(self):
        ip = _local_ip()
        assert ip not in ("0.0.0.0", "")


class TestCliLocalAgents:
    CLI_LOCAL = MARSRenderer._CLI_LOCAL_AGENTS

    @pytest.mark.parametrize("aid", ["echo-text", "echo-md", "echo-void"])
    def test_echo_agents_are_cli_local(self, aid):
        assert aid in self.CLI_LOCAL

    def test_cli_user_is_cli_local(self):
        assert "cli-user@1" in self.CLI_LOCAL

    @pytest.mark.parametrize("aid", ["svc.profiler@1", "svc.sympy@1", "llm.gpt4.1"])
    def test_service_agents_are_not_cli_local(self, aid):
        assert aid not in self.CLI_LOCAL


def test_render_sidebar_returns_panel():
    state = MARSState()
    state.agents = {
        "cli-user@1": AgentRecord(agent_id="cli-user@1", agent_type="HumanUser", platform="local"),
        "echo-md": AgentRecord(agent_id="echo-md", agent_type="EchoBot", platform="local"),
    }
    panel = MARSRenderer(state).render_sidebar()
    assert panel is not None
