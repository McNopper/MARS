"""Unit tests for the session save/restore agent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mars.runtime.agents.session_agent import _dispatch, _session_path


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    """Return a temp sessions directory (avoids touching ~/.mars/sessions/)."""
    return tmp_path / "sessions"


class TestSave:
    def test_save_named_session(self, storage: Path) -> None:
        result = _dispatch(storage, "save test-session")
        assert result["ok"] is True
        assert result["name"] == "test-session"
        assert _session_path(storage, "test-session").exists()

    def test_save_auto_name(self, storage: Path) -> None:
        result = _dispatch(storage, "save")
        assert result["ok"] is True
        assert result["name"].startswith("session-")

    def test_save_creates_dir(self, storage: Path) -> None:
        assert not storage.exists()
        _dispatch(storage, "save autosave")
        assert storage.exists()


class TestList:
    def test_list_empty(self, storage: Path) -> None:
        result = _dispatch(storage, "list")
        assert result["ok"] is True
        assert result["sessions"] == []

    def test_list_shows_saved_sessions(self, storage: Path) -> None:
        _dispatch(storage, "save alpha")
        _dispatch(storage, "save beta")
        result = _dispatch(storage, "list")
        assert result["ok"] is True
        names = [s["name"] for s in result["sessions"]]
        assert "alpha" in names
        assert "beta" in names


class TestLoad:
    def test_load_existing(self, storage: Path) -> None:
        _dispatch(storage, "save loadable")
        result = _dispatch(storage, "load loadable")
        assert result["ok"] is True
        assert result["data"]["name"] == "loadable"

    def test_load_nonexistent(self, storage: Path) -> None:
        result = _dispatch(storage, "load ghost")
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_load_returns_data_fields(self, storage: Path) -> None:
        _dispatch(storage, "save mytest")
        result = _dispatch(storage, "load mytest")
        assert "created_at" in result["data"]
        assert "updated_at" in result["data"]
        assert "messages" in result["data"]
        assert "agents" in result["data"]


class TestRename:
    def test_rename_success(self, storage: Path) -> None:
        _dispatch(storage, "save old-name")
        result = _dispatch(storage, "rename old-name new-name")
        assert result["ok"] is True
        assert not _session_path(storage, "old-name").exists()
        assert _session_path(storage, "new-name").exists()

    def test_rename_nonexistent(self, storage: Path) -> None:
        result = _dispatch(storage, "rename ghost nothing")
        assert result["ok"] is False
        assert "not found" in result["error"]


class TestDelete:
    def test_delete_existing(self, storage: Path) -> None:
        _dispatch(storage, "save to-delete")
        result = _dispatch(storage, "delete to-delete")
        assert result["ok"] is True
        assert not _session_path(storage, "to-delete").exists()

    def test_delete_nonexistent(self, storage: Path) -> None:
        result = _dispatch(storage, "delete ghost")
        assert result["ok"] is False


class TestInfo:
    def test_info_existing(self, storage: Path) -> None:
        _dispatch(storage, "save info-test")
        result = _dispatch(storage, "info info-test")
        assert result["ok"] is True
        assert result["name"] == "info-test"
        assert "created_at" in result
        assert "message_count" in result
        assert "data" not in result  # info should not return full data

    def test_info_nonexistent(self, storage: Path) -> None:
        result = _dispatch(storage, "info ghost")
        assert result["ok"] is False


class TestJsonForm:
    def test_json_save(self, storage: Path) -> None:
        payload = json.dumps({
            "op": "save",
            "name": "json-session",
            "data": {"messages": ["hello"], "agents": {}, "metadata": {"source": "test"}},
        })
        result = _dispatch(storage, payload)
        assert result["ok"] is True

        loaded = _dispatch(storage, "load json-session")
        assert loaded["ok"] is True
        assert loaded["data"]["messages"] == ["hello"]

    def test_json_list(self, storage: Path) -> None:
        _dispatch(storage, "save x")
        result = _dispatch(storage, json.dumps({"op": "list"}))
        assert result["ok"] is True

    def test_json_delete(self, storage: Path) -> None:
        _dispatch(storage, "save jdel")
        result = _dispatch(storage, json.dumps({"op": "delete", "name": "jdel"}))
        assert result["ok"] is True
