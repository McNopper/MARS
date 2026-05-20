"""Unit tests for the cross-session memory agent."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from mars.runtime.agents.memory_agent import _dispatch, _load, _save


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    """Return a temp storage directory (avoids touching ~/.mars/memory.json)."""
    return tmp_path


class TestRemember:
    def test_remember_with_key(self, storage: Path) -> None:
        result = _dispatch(storage, "remember project: MARS platform")
        assert result["ok"] is True
        assert result["key"] == "project"
        assert result["value"] == "MARS platform"

    def test_remember_without_key_autogenerates(self, storage: Path) -> None:
        result = _dispatch(storage, "remember This is a note")
        assert result["ok"] is True
        assert result["key"]  # auto-generated
        assert result["value"] == "This is a note"

    def test_remember_persists(self, storage: Path) -> None:
        _dispatch(storage, "remember lang: Python")
        data = _load(storage)
        assert "lang" in data
        assert data["lang"]["value"] == "Python"


class TestRecall:
    def test_recall_existing_key(self, storage: Path) -> None:
        _dispatch(storage, "remember color: blue")
        result = _dispatch(storage, "recall color")
        assert result["ok"] is True
        assert result["value"] == "blue"

    def test_recall_missing_key(self, storage: Path) -> None:
        result = _dispatch(storage, "recall nonexistent")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_recall_all(self, storage: Path) -> None:
        _dispatch(storage, "remember a: 1")
        _dispatch(storage, "remember b: 2")
        result = _dispatch(storage, "recall")
        assert result["ok"] is True
        assert result["count"] == 2
        keys = [f["key"] for f in result["facts"]]
        assert "a" in keys and "b" in keys

    def test_list_alias(self, storage: Path) -> None:
        _dispatch(storage, "remember x: y")
        result = _dispatch(storage, "list")
        assert result["ok"] is True
        assert result["count"] >= 1


class TestForget:
    def test_forget_specific_key(self, storage: Path) -> None:
        _dispatch(storage, "remember tmp: delete_me")
        result = _dispatch(storage, "forget tmp")
        assert result["ok"] is True
        data = _load(storage)
        assert "tmp" not in data

    def test_forget_all(self, storage: Path) -> None:
        _dispatch(storage, "remember a: 1")
        _dispatch(storage, "remember b: 2")
        result = _dispatch(storage, "forget all")
        assert result["ok"] is True
        data = _load(storage)
        assert data == {}

    def test_forget_clear_alias(self, storage: Path) -> None:
        _dispatch(storage, "remember z: 99")
        result = _dispatch(storage, "clear")
        assert result["ok"] is True

    def test_forget_nonexistent(self, storage: Path) -> None:
        result = _dispatch(storage, "forget nope")
        assert result["ok"] is False
        assert "not found" in result["error"]


class TestUpdateAt:
    def test_duplicate_remember_updates_updated_at(self, storage: Path) -> None:
        _dispatch(storage, "remember mykey: first")
        data_before = _load(storage)
        created_at = data_before["mykey"]["created_at"]

        time.sleep(0.01)
        _dispatch(storage, "remember mykey: second")
        data_after = _load(storage)
        assert data_after["mykey"]["value"] == "second"
        assert data_after["mykey"]["created_at"] == created_at
        assert data_after["mykey"]["updated_at"] >= data_after["mykey"]["created_at"]


class TestJsonForm:
    def test_json_remember(self, storage: Path) -> None:
        result = _dispatch(storage, json.dumps({"op": "remember", "key": "jk", "value": "jv"}))
        assert result["ok"] is True
        assert result["key"] == "jk"

    def test_json_recall(self, storage: Path) -> None:
        _dispatch(storage, json.dumps({"op": "remember", "key": "jp", "value": "jval"}))
        result = _dispatch(storage, json.dumps({"op": "recall", "key": "jp"}))
        assert result["ok"] is True
        assert result["value"] == "jval"

    def test_json_forget(self, storage: Path) -> None:
        _dispatch(storage, json.dumps({"op": "remember", "key": "jdel", "value": "x"}))
        result = _dispatch(storage, json.dumps({"op": "forget", "key": "jdel"}))
        assert result["ok"] is True

    def test_json_unknown_op(self, storage: Path) -> None:
        result = _dispatch(storage, json.dumps({"op": "explode"}))
        assert result["ok"] is False
