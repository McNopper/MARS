"""Unit tests for mars.runtime.agents.file_agent.

Covers:
- _safe_path: sandbox enforcement (path traversal blocked)
- _dispatch: all operations via plain text and JSON
- _normalize_file_request: natural-language to canonical form
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mars.runtime.agents.file_agent import (
    _dispatch,
    _normalize_file_request,
    _safe_path,
)


# ---------------------------------------------------------------------------
# _safe_path
# ---------------------------------------------------------------------------

class TestSafePath:
    def test_normal_path_allowed(self, tmp_path: Path) -> None:
        result = _safe_path(tmp_path, "notes.txt")
        assert result is not None
        assert result == tmp_path / "notes.txt"

    def test_subdir_allowed(self, tmp_path: Path) -> None:
        result = _safe_path(tmp_path, "subdir/notes.txt")
        assert result is not None

    def test_traversal_blocked(self, tmp_path: Path) -> None:
        result = _safe_path(tmp_path, "../etc/passwd")
        assert result is None

    def test_absolute_escape_blocked(self, tmp_path: Path) -> None:
        result = _safe_path(tmp_path, "/etc/passwd")
        # If absolute path doesn't sit inside tmp_path, must be None
        if result is not None:
            assert str(result).startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# _dispatch — plain text
# ---------------------------------------------------------------------------

class TestDispatchPlainText:
    def test_write_and_read(self, tmp_path: Path) -> None:
        r = _dispatch(tmp_path, "write hello.txt Hello World")
        assert r["ok"] is True
        assert r["op"] == "write"

        r = _dispatch(tmp_path, "read hello.txt")
        assert r["ok"] is True
        assert r["content"] == "Hello World"

    def test_append(self, tmp_path: Path) -> None:
        _dispatch(tmp_path, "write log.txt line1")
        r = _dispatch(tmp_path, "append log.txt \nline2")
        assert r["ok"] is True
        r = _dispatch(tmp_path, "read log.txt")
        assert "line1" in r["content"]
        assert "line2" in r["content"]

    def test_list_empty_dir(self, tmp_path: Path) -> None:
        r = _dispatch(tmp_path, "list .")
        assert r["ok"] is True
        assert isinstance(r["entries"], list)

    def test_list_after_write(self, tmp_path: Path) -> None:
        _dispatch(tmp_path, "write a.txt data")
        r = _dispatch(tmp_path, "list .")
        names = [e["name"] for e in r["entries"]]
        assert "a.txt" in names

    def test_delete(self, tmp_path: Path) -> None:
        _dispatch(tmp_path, "write del.txt bye")
        r = _dispatch(tmp_path, "delete del.txt")
        assert r["ok"] is True
        r = _dispatch(tmp_path, "read del.txt")
        assert r["ok"] is False

    def test_exists_true(self, tmp_path: Path) -> None:
        _dispatch(tmp_path, "write x.txt content")
        r = _dispatch(tmp_path, "exists x.txt")
        assert r["ok"] is True
        assert r["exists"] is True

    def test_exists_false(self, tmp_path: Path) -> None:
        r = _dispatch(tmp_path, "exists missing.txt")
        assert r["ok"] is True
        assert r["exists"] is False

    def test_mkdir(self, tmp_path: Path) -> None:
        r = _dispatch(tmp_path, "mkdir mydir")
        assert r["ok"] is True
        assert (tmp_path / "mydir").is_dir()

    def test_read_missing_file(self, tmp_path: Path) -> None:
        r = _dispatch(tmp_path, "read nonexistent.txt")
        assert r["ok"] is False
        assert "not found" in r["error"]

    def test_unknown_op(self, tmp_path: Path) -> None:
        r = _dispatch(tmp_path, "frobnicate something.txt")
        assert r["ok"] is False
        assert "unknown operation" in r["error"]


# ---------------------------------------------------------------------------
# _dispatch — JSON
# ---------------------------------------------------------------------------

class TestDispatchJSON:
    def test_write_and_read_json(self, tmp_path: Path) -> None:
        import json
        r = _dispatch(tmp_path, json.dumps({"op": "write", "path": "j.txt", "content": "hi"}))
        assert r["ok"] is True
        r = _dispatch(tmp_path, json.dumps({"op": "read", "path": "j.txt"}))
        assert r["content"] == "hi"

    def test_unknown_op_json(self, tmp_path: Path) -> None:
        import json
        r = _dispatch(tmp_path, json.dumps({"op": "explode", "path": "x.txt"}))
        assert r["ok"] is False

    def test_path_traversal_blocked_json(self, tmp_path: Path) -> None:
        import json
        r = _dispatch(tmp_path, json.dumps({"op": "read", "path": "../secret.txt"}))
        assert r["ok"] is False
        assert "sandbox" in r["error"]


# ---------------------------------------------------------------------------
# _normalize_file_request
# ---------------------------------------------------------------------------

class TestNormalizeFileRequest:
    def test_already_canonical_read(self) -> None:
        assert _normalize_file_request("read notes.txt") == "read notes.txt"

    def test_natural_read(self) -> None:
        assert _normalize_file_request("read the file notes.txt") == "read notes.txt"

    def test_show_file(self) -> None:
        assert _normalize_file_request("show notes.txt") == "read notes.txt"

    def test_save_as(self) -> None:
        result = _normalize_file_request("save Hello World as out.txt")
        assert result == "write out.txt Hello World"

    def test_list_files_in(self) -> None:
        result = _normalize_file_request("list files in data/")
        assert result.startswith("list")
        assert "data/" in result

    def test_delete_file(self) -> None:
        result = _normalize_file_request("delete the file notes.txt")
        assert result == "delete notes.txt"

    def test_check_if_exists(self) -> None:
        result = _normalize_file_request("check if notes.txt exists")
        assert result == "exists notes.txt"

    def test_create_directory(self) -> None:
        result = _normalize_file_request("create directory logs/")
        assert result == "mkdir logs/"

    def test_json_passthrough(self) -> None:
        cmd = '{"op": "read", "path": "x.txt"}'
        assert _normalize_file_request(cmd) == cmd
