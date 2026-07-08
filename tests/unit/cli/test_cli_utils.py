"""Unit tests for mars.cli.utils."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path


from mars.cli.utils import (
    _load_dotenv,
    _normalize_agent_type,
    _running_provider_names,
    _time_ago,
)
from mars.common.models import AgentRecord, MARSState


# ---------------------------------------------------------------------------
# _time_ago
# ---------------------------------------------------------------------------


class TestTimeAgo:
    def test_just_now_for_very_recent(self) -> None:
        dt = datetime.now() - timedelta(seconds=2)
        assert _time_ago(dt) == "just now"

    def test_seconds_ago(self) -> None:
        dt = datetime.now() - timedelta(seconds=30)
        result = _time_ago(dt)
        assert result.endswith("s ago")
        assert "30" in result

    def test_minutes_ago(self) -> None:
        dt = datetime.now() - timedelta(minutes=5)
        result = _time_ago(dt)
        assert result.endswith("m ago")
        assert "5" in result

    def test_hours_ago(self) -> None:
        dt = datetime.now() - timedelta(hours=3)
        result = _time_ago(dt)
        assert result.endswith("h ago")
        assert "3" in result

    def test_boundary_seconds_to_minutes(self) -> None:
        # exactly 60 seconds → should be "1m ago", not "60s ago"
        dt = datetime.now() - timedelta(seconds=61)
        result = _time_ago(dt)
        assert "m ago" in result

    def test_boundary_minutes_to_hours(self) -> None:
        # exactly 3600 seconds → "1h ago"
        dt = datetime.now() - timedelta(seconds=3601)
        result = _time_ago(dt)
        assert "h ago" in result


# ---------------------------------------------------------------------------
# _normalize_agent_type
# ---------------------------------------------------------------------------


class TestNormalizeAgentType:
    def test_cli_bridge_becomes_human_user(self) -> None:
        assert _normalize_agent_type("CLIBridgeAgent") == "HumanUser"

    def test_service_proxy_becomes_provider(self) -> None:
        assert _normalize_agent_type("ServiceProxyAgent") == "Provider"

    def test_unknown_type_passthrough(self) -> None:
        assert _normalize_agent_type("LLMAgent") == "LLMAgent"
        assert _normalize_agent_type("SomeCustomType") == "SomeCustomType"

    def test_empty_string_passthrough(self) -> None:
        assert _normalize_agent_type("") == ""


# ---------------------------------------------------------------------------
# _running_provider_names
# ---------------------------------------------------------------------------


class TestRunningProviderNames:
    def _state_with(self, agents: dict[str, str]) -> MARSState:
        state = MARSState()
        for aid, atype in agents.items():
            state.agents[aid] = AgentRecord(agent_id=aid, agent_type=atype)
        return state

    def test_llm_agents_excluded(self) -> None:
        state = self._state_with({"llm.1": "LLMAgent", "clock-provider": "Provider"})
        names = _running_provider_names(state)
        assert "llm.1" not in names

    def test_providers_included(self) -> None:
        state = self._state_with({"clock-provider": "Provider"})
        names = _running_provider_names(state)
        assert "clock-provider" in names

    def test_agent_suffix_stripped(self) -> None:
        state = self._state_with({"clock-agent": "Provider"})
        names = _running_provider_names(state)
        assert "clock" in names

    def test_provider_suffix_stripped(self) -> None:
        state = self._state_with({"clock-provider": "Provider"})
        names = _running_provider_names(state)
        assert "clock" in names

    def test_no_suffix_strip_for_non_agent_suffix(self) -> None:
        state = self._state_with({"profiler": "Provider"})
        names = _running_provider_names(state)
        assert "profiler" in names

    def test_echo_bot_excluded(self) -> None:
        state = self._state_with({"echo.1": "EchoBot"})
        names = _running_provider_names(state)
        assert len(names) == 0

    def test_human_user_excluded(self) -> None:
        state = self._state_with({"user.1": "HumanUser"})
        names = _running_provider_names(state)
        assert len(names) == 0

    def test_empty_state_returns_empty_set(self) -> None:
        state = MARSState()
        names = _running_provider_names(state)
        assert names == set()


# ---------------------------------------------------------------------------
# _load_dotenv
# ---------------------------------------------------------------------------


class TestLoadDotenv:
    def test_loads_key_value_pair(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("MY_TEST_KEY=my_test_value\n")
        os.environ.pop("MY_TEST_KEY", None)
        _load_dotenv(str(env_file))
        assert os.environ.get("MY_TEST_KEY") == "my_test_value"
        os.environ.pop("MY_TEST_KEY", None)

    def test_skips_comment_lines(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("# this is a comment\n#ANOTHER_COMMENT=ignored\n")
        _load_dotenv(str(env_file))  # should not crash or set spurious vars

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("\n\n\nFOO=bar\n")
        os.environ.pop("FOO", None)
        _load_dotenv(str(env_file))
        assert os.environ.get("FOO") == "bar"
        os.environ.pop("FOO", None)

    def test_strips_quotes_from_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_VAR="hello world"\n')
        os.environ.pop("QUOTED_VAR", None)
        _load_dotenv(str(env_file))
        assert os.environ.get("QUOTED_VAR") == "hello world"
        os.environ.pop("QUOTED_VAR", None)

    def test_strips_single_quotes_from_value(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("SINGLE_QUOTED='hello'\n")
        os.environ.pop("SINGLE_QUOTED", None)
        _load_dotenv(str(env_file))
        assert os.environ.get("SINGLE_QUOTED") == "hello"
        os.environ.pop("SINGLE_QUOTED", None)

    def test_does_not_overwrite_existing_env_var(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=new_value\n")
        os.environ["EXISTING_VAR"] = "original"
        _load_dotenv(str(env_file))
        assert os.environ["EXISTING_VAR"] == "original"
        os.environ.pop("EXISTING_VAR", None)

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        non_existent = str(tmp_path / "no_such.env")
        _load_dotenv(non_existent)  # should not raise

    def test_lines_without_equals_ignored(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("NOT_AN_ASSIGNMENT\n")
        _load_dotenv(str(env_file))  # should not raise
