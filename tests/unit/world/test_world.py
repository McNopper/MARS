"""Unit tests for the MARS world engine (text-file rooms, artifacts, inventory)."""
from __future__ import annotations

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
        world.create_room("library", "The Library", "Dusty shelves line the walls.")
        assert world.room_exists("library")
        assert "library" in world.list_rooms()

    def test_look_shows_description_present_and_items(self, world: World) -> None:
        world.create_room("library", "The Library", "Dusty shelves line the walls.")
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


class TestSafety:
    @pytest.mark.parametrize("bad", ["..", "../etc", "a/b", "", "a b", ".hidden"])
    def test_invalid_room_name_rejected(self, world: World, bad: str) -> None:
        with pytest.raises(ValueError):
            world.room_path(bad)

    @pytest.mark.parametrize("bad", ["../x", "a/b", "", " leading"])
    def test_invalid_item_name_rejected(self, world: World, bad: str) -> None:
        with pytest.raises(ValueError):
            world.take("lobby", "you", bad)
