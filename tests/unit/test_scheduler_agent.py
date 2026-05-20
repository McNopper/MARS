"""Unit tests for the scheduler agent."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mars.runtime.agents.scheduler_agent import (
    _dispatch,
    _parse_delay,
    _load,
)


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    """Temp storage dir — avoids touching ~/.mars/schedules.json."""
    return tmp_path


# ---------------------------------------------------------------------------
# _parse_delay
# ---------------------------------------------------------------------------

class TestParseDelay:
    def test_seconds(self) -> None:
        assert _parse_delay("30s") == 30.0

    def test_minutes(self) -> None:
        assert _parse_delay("5m") == 300.0

    def test_hours(self) -> None:
        assert _parse_delay("1h") == 3600.0

    def test_compound_2h30m(self) -> None:
        assert _parse_delay("2h30m") == 2 * 3600 + 30 * 60

    def test_compound_1h20m10s(self) -> None:
        assert _parse_delay("1h20m10s") == 3600 + 1200 + 10

    def test_pure_number_as_seconds(self) -> None:
        assert _parse_delay("60") == 60.0

    def test_invalid_returns_none(self) -> None:
        assert _parse_delay("abc") is None

    def test_empty_returns_none(self) -> None:
        assert _parse_delay("") is None


# ---------------------------------------------------------------------------
# Dispatch: after
# ---------------------------------------------------------------------------

class TestAfter:
    def test_basic_after(self, storage: Path) -> None:
        result = _dispatch(storage, "after 30s run tests")
        assert result["ok"] is True
        assert result["op"] == "after"
        assert result["delay_s"] == 30.0
        assert result["prompt"] == "run tests"
        assert result["id"].startswith("sched-")

    def test_after_persisted(self, storage: Path) -> None:
        _dispatch(storage, "after 60s check build")
        schedules = _load(storage)
        assert len(schedules) == 1
        assert schedules[0]["prompt"] == "check build"

    def test_after_minutes(self, storage: Path) -> None:
        result = _dispatch(storage, "after 5m send summary")
        assert result["ok"] is True
        assert result["delay_s"] == 300.0

    def test_after_invalid_delay(self, storage: Path) -> None:
        result = _dispatch(storage, "after baddelay do something")
        assert result["ok"] is False
        assert "invalid" in result["error"].lower()

    def test_after_missing_prompt(self, storage: Path) -> None:
        result = _dispatch(storage, "after 30s")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Dispatch: every
# ---------------------------------------------------------------------------

class TestEvery:
    def test_basic_every(self, storage: Path) -> None:
        result = _dispatch(storage, "every 10m ping me")
        assert result["ok"] is True
        assert result["op"] == "every"
        assert result["interval_s"] == 600.0
        assert "sched-" in result["id"]

    def test_every_persisted(self, storage: Path) -> None:
        _dispatch(storage, "every 5m heartbeat")
        schedules = _load(storage)
        assert any(s["type"] == "recurring" for s in schedules)


# ---------------------------------------------------------------------------
# Dispatch: list
# ---------------------------------------------------------------------------

class TestList:
    def test_list_empty(self, storage: Path) -> None:
        result = _dispatch(storage, "list")
        assert result["ok"] is True
        assert result["schedules"] == []
        assert result["count"] == 0

    def test_list_shows_schedules(self, storage: Path) -> None:
        _dispatch(storage, "after 30s task A")
        _dispatch(storage, "every 5m task B")
        result = _dispatch(storage, "list")
        assert result["ok"] is True
        assert result["count"] == 2

    def test_list_marks_due(self, storage: Path) -> None:
        result = _dispatch(storage, "after 0s immediate task")
        assert result["ok"] is True
        time.sleep(0.05)  # let it become due
        listed = _dispatch(storage, "list")
        due_items = [s for s in listed["schedules"] if s.get("due")]
        assert due_items


# ---------------------------------------------------------------------------
# Dispatch: cancel
# ---------------------------------------------------------------------------

class TestCancel:
    def test_cancel_existing(self, storage: Path) -> None:
        create = _dispatch(storage, "after 60s cancelme")
        sid = create["id"]
        result = _dispatch(storage, f"cancel {sid}")
        assert result["ok"] is True
        schedules = _load(storage)
        assert not any(s["id"] == sid for s in schedules)

    def test_cancel_nonexistent(self, storage: Path) -> None:
        result = _dispatch(storage, "cancel sched-doesnotexist")
        assert result["ok"] is False
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# JSON form
# ---------------------------------------------------------------------------

class TestJsonForm:
    def test_json_after(self, storage: Path) -> None:
        result = _dispatch(storage, json.dumps({
            "op": "after", "delay": 30, "prompt": "json prompt"
        }))
        assert result["ok"] is True
        assert result["delay_s"] == 30.0

    def test_json_every(self, storage: Path) -> None:
        result = _dispatch(storage, json.dumps({
            "op": "every", "interval": 120, "prompt": "recurring json"
        }))
        assert result["ok"] is True
        assert result["interval_s"] == 120.0

    def test_json_list(self, storage: Path) -> None:
        _dispatch(storage, json.dumps({"op": "after", "delay": 5, "prompt": "x"}))
        result = _dispatch(storage, json.dumps({"op": "list"}))
        assert result["ok"] is True
        assert result["count"] == 1

    def test_json_cancel(self, storage: Path) -> None:
        create = _dispatch(storage, json.dumps({"op": "after", "delay": 5, "prompt": "y"}))
        sid = create["id"]
        result = _dispatch(storage, json.dumps({"op": "cancel", "id": sid}))
        assert result["ok"] is True

    def test_json_unknown_op(self, storage: Path) -> None:
        result = _dispatch(storage, json.dumps({"op": "explode"}))
        assert result["ok"] is False
