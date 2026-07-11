"""Unit tests for the MARS world engine (text-file rooms, artifacts, inventory)."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mars.world.world import World


@pytest.fixture()
def world(tmp_path: Path) -> World:
    w = World(tmp_path / "world")
    w.init()
    return w


class TestRooms:
    def test_init_creates_default_rooms_dir_and_lobby(self, world: World) -> None:
        assert world.room_exists("lobby")
        assert "lobby" in world.list_rooms()
        assert (world.root / "rooms").is_dir()
        assert (world.root / "artifacts").is_dir()
        assert (world.root / "avatars").is_dir()

    def test_create_room_then_list_and_exists(self, world: World) -> None:
        world.create_room("cellar", "The Cellar", "Damp and dark.")
        assert world.room_exists("cellar")
        assert "cellar" in world.list_rooms()

    def test_look_shows_description_present_and_items(self, world: World) -> None:
        world.create_room("library", "The Library", "Dusty shelves line the walls.", exist_ok=True)
        world.put_item_in_room("library", "map.txt", "X marks the spot")
        view = world.look("library", present=["you", "dm"])
        assert "The Library" in view
        assert "Dusty shelves" in view
        assert "Present: dm, you" in view
        assert "Items: map.txt" in view

    def test_look_omits_present_and_items_when_empty(self, world: World) -> None:
        view = world.look("lobby")
        assert "Present" not in view
        assert "Items" not in view

    def test_look_unknown_room_lists_alternatives(self, world: World) -> None:
        view = world.look("cellar")
        assert "no room" in view.lower()
        assert "lobby" in view


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

    def test_prune_removes_expired_lines(self, world: World) -> None:
        world.create_room("cellar", "The Cellar", "damp")
        old = (datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds")
        world.room_path("cellar").write_text(
            f"# The Cellar\n\ndamp\n\n---\n{old}\ta: stale\n", encoding="utf-8"
        )
        assert world.prune_room("cellar", ttl_seconds=60) == 1
        assert world.listen("cellar") == "(silence)"

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


class TestItemsAndInventory:
    def test_take_moves_item_from_room_to_inventory(self, world: World) -> None:
        world.put_item_in_room("lobby", "map.txt", "X")
        assert "map.txt" in world.items_in_room("lobby")
        world.take("lobby", "you", "map.txt")
        assert "map.txt" not in world.items_in_room("lobby")
        assert "map.txt" in world.inventory("you")

    def test_take_unknown_item_raises(self, world: World) -> None:
        with pytest.raises(FileNotFoundError):
            world.take("lobby", "you", "nope.txt")

    def test_drop_moves_item_back_to_room(self, world: World) -> None:
        world.put_item_in_room("lobby", "map.txt", "X")
        world.take("lobby", "you", "map.txt")
        world.drop("you", "lobby", "map.txt")
        assert "map.txt" in world.items_in_room("lobby")
        assert "map.txt" not in world.inventory("you")

    def test_drop_not_carried_raises(self, world: World) -> None:
        with pytest.raises(FileNotFoundError):
            world.drop("you", "lobby", "map.txt")

    def test_item_can_only_be_taken_once(self, world: World) -> None:
        world.put_item_in_room("lobby", "book.txt", "pages")
        world.take("lobby", "alice", "book.txt")
        assert world.inventory("alice") == ["book.txt"]
        with pytest.raises(FileNotFoundError):
            world.take("lobby", "bob", "book.txt")
        assert world.inventory("bob") == []

    def test_taken_item_moves_to_taker_and_is_examinable(self, world: World) -> None:
        world.put_item_in_room("lobby", "book.txt", "pages")
        world.take("lobby", "alice", "book.txt")
        assert world.read_carried("alice", "book.txt") == "pages"
        with pytest.raises(FileNotFoundError):
            world.read_item("lobby", "book.txt")

    def test_take_refuses_to_overwrite_carried_item(self, world: World) -> None:
        world.put_item_in_room("lobby", "map.txt", "v1")
        world.take("lobby", "alice", "map.txt")
        world.put_item_in_room("lobby", "map.txt", "v2")
        with pytest.raises(FileExistsError):
            world.take("lobby", "alice", "map.txt")
        assert world.read_carried("alice", "map.txt") == "v1"

    def test_drop_refuses_to_overwrite_room_item(self, world: World) -> None:
        world.put_item_in_room("lobby", "map.txt", "carried")
        world.take("lobby", "alice", "map.txt")
        world.put_item_in_room("lobby", "map.txt", "already-here")
        with pytest.raises(FileExistsError):
            world.drop("alice", "lobby", "map.txt")

    def test_create_item_is_exclusive(self, world: World) -> None:
        world.create_item("lobby", "note.txt", "first")
        with pytest.raises(FileExistsError):
            world.create_item("lobby", "note.txt", "second")
        assert world.read_item("lobby", "note.txt") == "first"

    def test_create_room_refuses_existing_unless_forced(self, world: World) -> None:
        with pytest.raises(FileExistsError):
            world.create_room("lobby", "The Lobby", "overwritten")
        world.create_room("lobby", "The Lobby", "overwritten", exist_ok=True)
        assert "overwritten" in world.look("lobby")


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

    def test_concurrent_takers_only_one_wins(self, world: World) -> None:
        world.put_item_in_room("lobby", "gem.txt", "shiny")
        winners: list[int] = []
        guard = threading.Lock()

        def taker(i: int) -> None:
            try:
                world.take("lobby", f"a{i}", "gem.txt")
            except FileNotFoundError:
                return
            except FileExistsError:
                return
            with guard:
                winners.append(i)

        threads = [threading.Thread(target=taker, args=(i,)) for i in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(winners) == 1


class TestSafety:
    @pytest.mark.parametrize("bad", ["..", "../etc", "a/b", "", "a b", ".hidden"])
    def test_invalid_room_name_rejected(self, world: World, bad: str) -> None:
        with pytest.raises(ValueError):
            world.room_path(bad)

    @pytest.mark.parametrize("bad", ["../x", "a/b", "", " leading"])
    def test_invalid_item_name_rejected(self, world: World, bad: str) -> None:
        with pytest.raises(ValueError):
            world.take("lobby", "you", bad)
