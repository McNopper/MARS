"""Unit tests for mars.storage.artifacts.artifact.Artifact and mars.storage.artifacts.store.ArtifactStore.

Covers:
- from_path: reads file, detects MIME type, creates Artifact
- from_directory: zips directory, zip MIME type
- from_zip_dict: handles str and bytes values
- summary(): contains expected fields, no binary data
- to_path: writes bytes to disk
- is_text: True for common text types
- ArtifactStore.delete: returns False when artifact not found
- ArtifactStore.list_by_creator: filters correctly
- ArtifactStore.size: tracks count
"""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from mars.storage.artifacts.artifact import Artifact
from mars.storage.artifacts.store import ArtifactStore


# ---------------------------------------------------------------------------
# Artifact.from_path
# ---------------------------------------------------------------------------


class TestArtifactFromPath:
    def test_reads_file_content(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")
        art = Artifact.from_path(f)
        assert art.data == b"hello world"
        assert art.name == "hello.txt"

    def test_detects_text_mime_type(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("content", encoding="utf-8")
        art = Artifact.from_path(f)
        assert art.mime_type == "text/plain"

    def test_detects_json_mime_type(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text('{"key": 1}', encoding="utf-8")
        art = Artifact.from_path(f)
        assert art.mime_type == "application/json"

    def test_unknown_extension_falls_back_to_octet_stream(self, tmp_path: Path) -> None:
        f = tmp_path / "file.xyzabc"
        f.write_bytes(b"\x00\x01\x02")
        art = Artifact.from_path(f)
        assert art.mime_type == "application/octet-stream"

    def test_sets_created_by(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("hi")
        art = Artifact.from_path(f, created_by="agent.1")
        assert art.created_by == "agent.1"


# ---------------------------------------------------------------------------
# Artifact.from_directory
# ---------------------------------------------------------------------------


class TestArtifactFromDirectory:
    def test_creates_zip_with_correct_mime(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        art = Artifact.from_directory(tmp_path)
        assert art.mime_type == "application/zip"
        assert art.name.endswith(".zip")

    def test_zip_contains_all_files(self, tmp_path: Path) -> None:
        (tmp_path / "hello.py").write_text("print('hi')")
        (tmp_path / "readme.md").write_text("# readme")
        art = Artifact.from_directory(tmp_path)
        contents = art.list_zip_contents()
        assert contents is not None
        names = set(contents)
        assert "hello.py" in names
        assert "readme.md" in names

    def test_raises_for_non_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("text")
        with pytest.raises(ValueError, match="Not a directory"):
            Artifact.from_directory(f)

    def test_archive_name_default(self, tmp_path: Path) -> None:
        (tmp_path / "x.txt").write_text("x")
        art = Artifact.from_directory(tmp_path)
        assert art.name == f"{tmp_path.name}.zip"

    def test_archive_name_custom(self, tmp_path: Path) -> None:
        (tmp_path / "x.txt").write_text("x")
        art = Artifact.from_directory(tmp_path, archive_name="custom.zip")
        assert art.name == "custom.zip"


# ---------------------------------------------------------------------------
# Artifact.from_zip_dict
# ---------------------------------------------------------------------------


class TestArtifactFromZipDict:
    def test_handles_str_values(self) -> None:
        art = Artifact.from_zip_dict("out.zip", {"main.py": "print('hi')"})
        assert art.mime_type == "application/zip"
        contents = art.list_zip_contents()
        assert "main.py" in (contents or [])

    def test_handles_bytes_values(self) -> None:
        art = Artifact.from_zip_dict("out.zip", {"data.bin": b"\x00\x01"})
        contents = art.list_zip_contents()
        assert "data.bin" in (contents or [])

    def test_mixed_str_and_bytes(self) -> None:
        files = {"readme.md": "# README", "data.bin": b"\xff\xfe"}
        art = Artifact.from_zip_dict("mixed.zip", files)
        contents = set(art.list_zip_contents() or [])
        assert contents == {"readme.md", "data.bin"}


# ---------------------------------------------------------------------------
# Artifact.summary()
# ---------------------------------------------------------------------------


class TestArtifactSummary:
    def _art(self) -> Artifact:
        return Artifact.from_text("report.txt", "content", created_by="agent.1")

    def test_summary_contains_artifact_id(self) -> None:
        art = self._art()
        s = art.summary()
        assert "artifact_id" in s
        assert s["artifact_id"] == art.artifact_id

    def test_summary_contains_name(self) -> None:
        art = self._art()
        assert art.summary()["name"] == "report.txt"

    def test_summary_contains_mime_type(self) -> None:
        art = self._art()
        assert "mime_type" in art.summary()

    def test_summary_contains_size(self) -> None:
        art = self._art()
        assert "size" in art.summary()
        assert isinstance(art.summary()["size"], int)

    def test_summary_contains_checksum_sha256(self) -> None:
        art = self._art()
        s = art.summary()
        assert "checksum_sha256" in s
        assert len(s["checksum_sha256"]) == 64  # SHA-256 hex digest length

    def test_summary_contains_created_by(self) -> None:
        art = self._art()
        assert art.summary()["created_by"] == "agent.1"

    def test_summary_has_no_raw_bytes(self) -> None:
        art = self._art()
        s = art.summary()
        assert "data" not in s


# ---------------------------------------------------------------------------
# Artifact.to_path
# ---------------------------------------------------------------------------


class TestArtifactToPath:
    def test_writes_bytes_to_disk(self, tmp_path: Path) -> None:
        art = Artifact.from_text("hello.txt", "hello world")
        out = tmp_path / "output" / "hello.txt"
        art.to_path(out)
        assert out.read_bytes() == b"hello world"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        art = Artifact(name="x.bin", data=b"\x01\x02")
        out = tmp_path / "a" / "b" / "c" / "x.bin"
        art.to_path(out)
        assert out.exists()


# ---------------------------------------------------------------------------
# Artifact.is_text
# ---------------------------------------------------------------------------


class TestArtifactIsText:
    def test_text_plain_is_text(self) -> None:
        art = Artifact(name="f.txt", data=b"hi", mime_type="text/plain")
        assert art.is_text() is True

    def test_text_markdown_is_text(self) -> None:
        art = Artifact(name="f.md", data=b"# hi", mime_type="text/markdown")
        assert art.is_text() is True

    def test_application_json_is_text(self) -> None:
        art = Artifact(name="f.json", data=b"{}", mime_type="application/json")
        assert art.is_text() is True

    def test_application_zip_is_not_text(self) -> None:
        art = Artifact(name="f.zip", data=b"PK", mime_type="application/zip")
        assert art.is_text() is False

    def test_image_jpeg_is_not_text(self) -> None:
        art = Artifact(name="f.jpg", data=b"\xff\xd8", mime_type="image/jpeg")
        assert art.is_text() is False


# ---------------------------------------------------------------------------
# ArtifactStore
# ---------------------------------------------------------------------------


class TestArtifactStore:
    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self) -> None:
        store = ArtifactStore()
        art = Artifact.from_text("file.txt", "hello")
        aid = await store.put(art)
        retrieved = await store.get(aid)
        assert retrieved is not None
        assert retrieved.name == "file.txt"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self) -> None:
        store = ArtifactStore()
        result = await store.get("does-not-exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_exists(self) -> None:
        store = ArtifactStore()
        art = Artifact.from_text("x.txt", "x")
        aid = await store.put(art)
        assert await store.delete(aid) is True

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_missing(self) -> None:
        store = ArtifactStore()
        assert await store.delete("not-here") is False

    @pytest.mark.asyncio
    async def test_list_by_creator_filters_correctly(self) -> None:
        store = ArtifactStore()
        a1 = Artifact.from_text("a.txt", "a", created_by="agent.1")
        a2 = Artifact.from_text("b.txt", "b", created_by="agent.2")
        a3 = Artifact.from_text("c.txt", "c", created_by="agent.1")
        for a in (a1, a2, a3):
            await store.put(a)
        by_agent1 = await store.list_by_creator("agent.1")
        assert len(by_agent1) == 2
        assert all(a.created_by == "agent.1" for a in by_agent1)

    @pytest.mark.asyncio
    async def test_size_tracks_count(self) -> None:
        store = ArtifactStore()
        assert await store.size() == 0
        await store.put(Artifact.from_text("a.txt", "a"))
        assert await store.size() == 1
        await store.put(Artifact.from_text("b.txt", "b"))
        assert await store.size() == 2

    @pytest.mark.asyncio
    async def test_list_summaries_no_binary_data(self) -> None:
        store = ArtifactStore()
        await store.put(Artifact.from_text("report.txt", "content"))
        summaries = await store.list_summaries()
        assert len(summaries) == 1
        assert "data" not in summaries[0]

    @pytest.mark.asyncio
    async def test_list_summaries_filtered_by_creator(self) -> None:
        store = ArtifactStore()
        await store.put(Artifact.from_text("a.txt", "a", created_by="bot.1"))
        await store.put(Artifact.from_text("b.txt", "b", created_by="bot.2"))
        result = await store.list_summaries(creator="bot.1")
        assert len(result) == 1
        assert result[0]["created_by"] == "bot.1"
