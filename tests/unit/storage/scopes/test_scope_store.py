"""Unit tests for mars.storage.scopes.store.ScopeStore.

Covers:
- load_all() returns empty list when root is missing
- next_id() returns S1 for first root scope
- next_id() increments correctly for subsequent root scopes
- next_id() returns S1.1 for first child of S1
- write() creates nested path on disk
- _extract_title() uses first # heading
- _extract_title() falls back to first text line
- children of a scope have correct parent_id
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mars.storage.scopes.store import ScopeStore


# ---------------------------------------------------------------------------
# load_all
# ---------------------------------------------------------------------------


class TestScopeStoreLoadAll:
    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        store = ScopeStore(tmp_path / "no_such_dir")
        assert store.load_all() == []

    def test_loads_single_scope(self, tmp_path: Path) -> None:
        (tmp_path / "S1.md").write_text("# Scope One\nContent.", encoding="utf-8")
        store = ScopeStore(tmp_path)
        scopes = store.load_all()
        assert len(scopes) == 1
        assert scopes[0].id == "S1"

    def test_loads_hierarchy(self, tmp_path: Path) -> None:
        (tmp_path / "S1.md").write_text("# Root", encoding="utf-8")
        sub = tmp_path / "S1"
        sub.mkdir()
        (sub / "S1.1.md").write_text("# Child", encoding="utf-8")
        store = ScopeStore(tmp_path)
        scopes = store.load_all()
        ids = {s.id for s in scopes}
        assert "S1" in ids
        assert "S1.1" in ids

    def test_child_has_correct_parent_id(self, tmp_path: Path) -> None:
        (tmp_path / "S1.md").write_text("# Root", encoding="utf-8")
        sub = tmp_path / "S1"
        sub.mkdir()
        (sub / "S1.1.md").write_text("# Child", encoding="utf-8")
        store = ScopeStore(tmp_path)
        scopes = {s.id: s for s in store.load_all()}
        assert scopes["S1"].parent_id is None
        assert scopes["S1.1"].parent_id == "S1"

    def test_path_uses_forward_slashes(self, tmp_path: Path) -> None:
        sub = tmp_path / "S1"
        sub.mkdir()
        (tmp_path / "S1.md").write_text("# Root")
        (sub / "S1.1.md").write_text("# Child")
        store = ScopeStore(tmp_path)
        scopes = {s.id: s for s in store.load_all()}
        assert "\\" not in scopes["S1.1"].path


# ---------------------------------------------------------------------------
# next_id
# ---------------------------------------------------------------------------


class TestScopeStoreNextId:
    def test_next_id_root_empty_is_s1(self, tmp_path: Path) -> None:
        store = ScopeStore(tmp_path)
        assert store.next_id() == "S1"

    def test_next_id_root_increments(self, tmp_path: Path) -> None:
        (tmp_path / "S1.md").write_text("# One")
        (tmp_path / "S2.md").write_text("# Two")
        store = ScopeStore(tmp_path)
        assert store.next_id() == "S3"

    def test_next_id_child_empty_is_first(self, tmp_path: Path) -> None:
        (tmp_path / "S1.md").write_text("# One")
        store = ScopeStore(tmp_path)
        assert store.next_id(parent_id="S1") == "S1.1"

    def test_next_id_child_increments(self, tmp_path: Path) -> None:
        (tmp_path / "S1.md").write_text("# One")
        sub = tmp_path / "S1"
        sub.mkdir()
        (sub / "S1.1.md").write_text("# First")
        store = ScopeStore(tmp_path)
        assert store.next_id(parent_id="S1") == "S1.2"


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


class TestScopeStoreWrite:
    def test_write_creates_file_at_root(self, tmp_path: Path) -> None:
        store = ScopeStore(tmp_path)
        path = store.write("S1", "# Scope One\nContent.")
        assert path.exists()
        assert path.name == "S1.md"

    def test_write_creates_nested_path_for_child(self, tmp_path: Path) -> None:
        store = ScopeStore(tmp_path)
        path = store.write("S1.1", "# Child scope", parent_id="S1")
        assert path.exists()
        assert path.parent.name == "S1"

    def test_written_scope_is_loadable(self, tmp_path: Path) -> None:
        store = ScopeStore(tmp_path)
        store.write("S1", "# Test Scope\nBody text.")
        scopes = store.load_all()
        assert any(s.id == "S1" for s in scopes)


# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_uses_first_heading(self) -> None:
        doc = "# My Scope Title\nSome content."
        title = ScopeStore._extract_title(doc, "fallback")
        assert title == "My Scope Title"

    def test_uses_second_level_heading(self) -> None:
        doc = "## Sub-title\nContent."
        title = ScopeStore._extract_title(doc, "fallback")
        assert title == "Sub-title"

    def test_falls_back_to_first_text_line(self) -> None:
        doc = "No heading here\nSecond line."
        title = ScopeStore._extract_title(doc, "fallback")
        assert title == "No heading here"

    def test_falls_back_to_scope_id_when_empty(self) -> None:
        title = ScopeStore._extract_title("", "S99")
        assert title == "S99"

    def test_strips_hash_and_spaces(self) -> None:
        doc = "#   Padded Title  \nBody."
        title = ScopeStore._extract_title(doc, "fb")
        assert title == "Padded Title"
