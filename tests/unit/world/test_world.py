"""Unit tests for the MARS world engine (text-file rooms: description + protocol + transcript)."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mars.world.world import MAX_READ_CHARS, World


@pytest.fixture()
def world(tmp_path: Path) -> World:
    w = World(tmp_path / "world")
    w.init()
    return w


class TestRooms:
    def test_init_seeds_only_lobby(self, world: World) -> None:
        assert world.room_exists("lobby")
        assert "lobby" in world.list_rooms()
        assert (world.root / "rooms").is_dir()
        assert world.list_rooms() == ["lobby"]  # nothing else seeded; the rest is dynamic

    def test_no_artifacts_or_avatars_dirs(self, world: World) -> None:
        assert not (world.root / "artifacts").exists()
        assert not (world.root / "avatars").exists()

    def test_create_room_then_list_and_exists(self, world: World) -> None:
        world.create_room("cellar", "The Cellar", "Damp and dark.")
        assert world.room_exists("cellar")
        assert "cellar" in world.list_rooms()

    def test_create_room_rejects_empty_title(self, world: World) -> None:
        with pytest.raises(ValueError):
            world.create_room("cellar", "   ", "Damp and dark.")

    def test_create_room_rejects_separator_in_description(self, world: World) -> None:
        with pytest.raises(ValueError):
            world.create_room("cellar", "The Cellar", "Damp.\n\n---\n\nDark.")

    def test_create_room_existing_raises_unless_forced(self, world: World) -> None:
        with pytest.raises(FileExistsError):
            world.create_room("lobby", "x", "y")
        world.create_room("lobby", "The Lobby", "overwritten", exist_ok=True)
        assert "overwritten" in world.look("lobby")

    def test_empty_description_defaults_to_title(self, world: World) -> None:
        world.create_room("void", "The Void", "")
        view = world.look("void")
        assert "The Void" in view  # title and description both present


class TestLook:
    def test_shows_description_and_present(self, world: World) -> None:
        view = world.look("lobby", present=["you", "dm"])
        assert "The Lobby" in view
        assert "Present: dm, you" in view
        assert "Protocol" not in view  # empty protocol → no hint

    def test_hints_at_protocol_when_present(self, world: World) -> None:
        world.write_protocol("lobby", "1. be kind\n2. be brief")
        view = world.look("lobby")
        assert "Protocol: 2 line(s)" in view

    def test_unknown_room_lists_alternatives(self, world: World) -> None:
        view = world.look("cellar")
        assert "no room" in view.lower()
        assert "lobby" in view


class TestProtocol:
    def test_read_empty_protocol(self, world: World) -> None:
        assert world.read_protocol("lobby") == "(no protocol yet — write one)"

    def test_write_then_read(self, world: World) -> None:
        world.write_protocol("lobby", "# Charter\n\n1. be kind")
        assert world.read_protocol("lobby") == "# Charter\n\n1. be kind"

    def test_write_replaces(self, world: World) -> None:
        world.write_protocol("lobby", "v1")
        world.write_protocol("lobby", "v2")
        assert world.read_protocol("lobby") == "v2"

    def test_write_empty_clears(self, world: World) -> None:
        world.write_protocol("lobby", "the rules")
        world.write_protocol("lobby", "")
        assert world.read_protocol("lobby") == "(no protocol yet — write one)"

    def test_append_merges(self, world: World) -> None:
        world.write_protocol("lobby", "one")
        world.append_protocol("lobby", "two")
        assert world.read_protocol("lobby") == "one\n\ntwo"

    def test_append_to_empty(self, world: World) -> None:
        world.append_protocol("lobby", "first")
        assert world.read_protocol("lobby") == "first"

    def test_write_rejects_separator_line(self, world: World) -> None:
        with pytest.raises(ValueError):
            world.write_protocol("lobby", "above\n\n---\n\nbelow")
        assert world.read_protocol("lobby") == "(no protocol yet — write one)"  # nothing written

    def test_append_rejects_separator_line(self, world: World) -> None:
        world.write_protocol("lobby", "keep")
        with pytest.raises(ValueError):
            world.append_protocol("lobby", "---")
        assert world.read_protocol("lobby") == "keep"  # unchanged

    def test_read_caps_huge_protocol(self, world: World) -> None:
        world.write_protocol("lobby", "x" * (MAX_READ_CHARS + 100))
        out = world.read_protocol("lobby")
        assert "truncated" in out
        assert len(out) < MAX_READ_CHARS + 200

    def test_protocol_survives_chat_and_prune(self, world: World) -> None:
        world.write_protocol("lobby", "the contract")
        world.say("lobby", "you", "hello")
        assert world.prune_room("lobby", ttl_seconds=60) == 0  # fresh line kept
        assert world.read_protocol("lobby") == "the contract"
        assert "you: hello" in world.listen("lobby")

    def test_read_unknown_room_raises(self, world: World) -> None:
        with pytest.raises(FileNotFoundError):
            world.read_protocol("cellar")

    def test_write_unknown_room_raises(self, world: World) -> None:
        with pytest.raises(FileNotFoundError):
            world.write_protocol("cellar", "x")


class TestTranscript:
    def test_listen_on_silent_room(self, world: World) -> None:
        assert world.listen("lobby") == "(silence)"

    def test_say_appends_and_listen_returns_tail(self, world: World) -> None:
        world.say("lobby", "you", "hello world")
        world.say("lobby", "dm", "welcome, traveler")
        transcript = world.listen("lobby")
        assert "you: hello world" in transcript
        assert "dm: welcome, traveler" in transcript

    def test_say_is_timestamped_but_listen_strips_it(self, world: World) -> None:
        world.say("lobby", "you", "marked")
        raw = world.room_path("lobby").read_text(encoding="utf-8")
        assert "\t" in raw                       # timestamp stored in the file
        assert "you: marked" in world.listen("lobby")
        assert "\t" not in world.listen("lobby")  # ...but stripped for display

    def test_prune_keeps_fresh_lines(self, world: World) -> None:
        world.say("lobby", "you", "fresh")
        assert world.prune_room("lobby", ttl_seconds=60) == 0
        assert "fresh" in world.listen("lobby")

    def test_prune_removes_expired_lines_and_preserves_protocol(self, world: World) -> None:
        world.create_room("cellar", "The Cellar", "damp")
        world.write_protocol("cellar", "survives pruning")
        old = (datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds")
        world.room_path("cellar").write_text(
            f"# The Cellar\n\ndamp\n\n---\n\nsurvives pruning\n\n---\n{old}\ta: stale\n", encoding="utf-8"
        )
        assert world.prune_room("cellar", ttl_seconds=60) == 1
        assert world.listen("cellar") == "(silence)"
        assert world.read_protocol("cellar") == "survives pruning"

    def test_listen_filters_by_ttl(self, world: World) -> None:
        world.create_room("cellar", "The Cellar", "damp")
        old = (datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds")
        world.room_path("cellar").write_text(
            f"# The Cellar\n\ndamp\n\n---\n{old}\ta: stale\n", encoding="utf-8"
        )
        assert "stale" not in world.listen("cellar", ttl_seconds=60)
        assert "stale" in world.listen("cellar", ttl_seconds=None)

    def test_listen_respects_line_limit(self, world: World) -> None:
        for i in range(10):
            world.say("lobby", "you", f"line {i}")
        tail = world.listen("lobby", lines=3)
        assert tail.splitlines() == ["you: line 7", "you: line 8", "you: line 9"]

    def test_say_to_unknown_room_raises(self, world: World) -> None:
        with pytest.raises(FileNotFoundError):
            world.say("cellar", "you", "echo")

    def test_transcript_persists_to_disk(self, world: World) -> None:
        world.say("lobby", "you", "persisted")
        raw = world.room_path("lobby").read_text(encoding="utf-8")
        assert "you: persisted" in raw
        reload = World(world.root)
        assert "you: persisted" in reload.listen("lobby")


class TestLegacyFormat:
    def test_two_section_file_reads_as_description_and_transcript(self, world: World) -> None:
        path = world.room_path("lobby")
        path.write_text("# Old\n\nlegacy desc\n\n---\n2020-01-01T00:00:00\tyou: hi\n", encoding="utf-8")
        assert "legacy desc" in world.look("lobby")
        assert world.read_protocol("lobby") == "(no protocol yet — write one)"
        assert "you: hi" in world.listen("lobby")

    def test_writing_protocol_upgrades_to_three_sections(self, world: World) -> None:
        path = world.room_path("lobby")
        path.write_text("# Old\n\nlegacy desc\n\n---\n2020-01-01T00:00:00\tyou: hi\n", encoding="utf-8")
        world.write_protocol("lobby", "new deal")
        assert world.read_protocol("lobby") == "new deal"
        assert "you: hi" in world.listen("lobby")  # transcript preserved
        assert "legacy desc" in world.look("lobby")  # description preserved


class TestConcurrency:
    def test_concurrent_says_lose_no_lines(self, world: World) -> None:
        n_speakers, msgs_each = 16, 8
        expected = n_speakers * msgs_each

        def speaker(i: int) -> None:
            for j in range(msgs_each):
                world.say("lobby", f"a{i}", f"msg-{i}-{j}")

        threads = [threading.Thread(target=speaker, args=(i,)) for i in range(n_speakers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        transcript = world.listen("lobby", lines=expected * 2)
        assert transcript.count("msg-") == expected

    def test_concurrent_appends_lose_no_lines(self, world: World) -> None:
        n, each = 16, 8
        expected = n * each

        def appender(i: int) -> None:
            for j in range(each):
                world.append_protocol("lobby", f"p-{i}-{j}")

        threads = [threading.Thread(target=appender, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        protocol = world.read_protocol("lobby")
        assert protocol.count("p-") == expected


class TestSafety:
    @pytest.mark.parametrize("bad", ["..", "../etc", "a/b", "", "a b", ".hidden"])
    def test_invalid_room_name_rejected(self, world: World, bad: str) -> None:
        with pytest.raises(ValueError):
            world.room_path(bad)
