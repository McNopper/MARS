"""Unit tests for WorldSession — presence and the verb surface over a World."""
from __future__ import annotations

from pathlib import Path

import pytest

from mars.world.world import World
from mars.world.server import WorldSession


@pytest.fixture()
def session(tmp_path: Path) -> WorldSession:
    w = World(tmp_path / "world")
    w.init()
    return WorldSession(w)


class TestPresence:
    def test_avatar_defaults_to_lobby(self, session: WorldSession) -> None:
        view = session.look("you")
        assert "Lobby" in view

    def test_go_changes_room_and_context(self, session: WorldSession) -> None:
        session.go("you", "library")
        assert "Library" in session.look("you")

    def test_go_unknown_room_is_friendly(self, session: WorldSession) -> None:
        msg = session.go("you", "cellar")
        assert "no room" in msg.lower()
        assert "lobby" in msg

    def test_present_avatars_appear_in_look(self, session: WorldSession) -> None:
        session.go("you", "library")
        session.go("dm", "library")
        view = session.look("you")
        assert "Present: dm, you" in view


class TestSpeechAcrossAvatars:
    def test_one_avatar_speaks_another_listens(self, session: WorldSession) -> None:
        session.go("you", "library")
        session.go("dm", "library")
        session.say("dm", "welcome, traveler")
        heard = session.listen("you")
        assert "dm: welcome, traveler" in heard

    def test_speech_only_in_current_room(self, session: WorldSession) -> None:
        session.go("you", "library")
        session.say("you", "hello from the library")
        session.go("you", "lobby")
        assert "hello from the library" not in session.listen("you")


class TestItemsThroughSession:
    def test_take_then_inventory_then_drop(self, session: WorldSession) -> None:
        session.world.put_item_in_room("lobby", "map.txt", "X")
        assert "Taken" in session.take("you", "map.txt")
        assert "map.txt" in session.inventory("you")
        session.go("you", "library")
        assert "Dropped" in session.drop("you", "map.txt")
        assert "nothing" in session.inventory("you")

    def test_take_missing_item_is_friendly(self, session: WorldSession) -> None:
        assert "Could not take" in session.take("you", "ghost.txt")

    def test_second_taker_is_told_the_item_is_gone(self, session: WorldSession) -> None:
        session.world.put_item_in_room("lobby", "book.txt", "pages")
        session.go("alice", "lobby")
        session.go("bob", "lobby")
        assert "Taken" in session.take("alice", "book.txt")
        result = session.take("bob", "book.txt")
        assert "Could not take" in result

    def test_examine_reads_item_in_room(self, session: WorldSession) -> None:
        session.world.put_item_in_room("lobby", "note.txt", "the password is 1234")
        assert "the password is 1234" in session.examine("you", "note.txt")

    def test_examine_reads_carried_item_after_take(self, session: WorldSession) -> None:
        session.world.put_item_in_room("lobby", "note.txt", "secret")
        session.take("you", "note.txt")
        assert "secret" in session.examine("you", "note.txt")

    def test_examine_missing_item_is_friendly(self, session: WorldSession) -> None:
        assert "no 'ghost.txt'" in session.examine("you", "ghost.txt")


def test_rooms_lists_all(session: WorldSession) -> None:
    assert "lobby" in session.rooms()
    assert "library" in session.rooms()


class TestAuthoring:
    def test_create_then_examine_then_destroy(self, session: WorldSession) -> None:
        assert "Created" in session.create("you", "note.txt", "hello world")
        assert "hello world" in session.examine("you", "note.txt")
        assert "Destroyed" in session.destroy("you", "note.txt")
        assert "no 'note.txt'" in session.examine("you", "note.txt")

    def test_create_duplicate_refused(self, session: WorldSession) -> None:
        session.create("you", "note.txt", "v1")
        msg = session.create("you", "note.txt", "v2")
        assert "already exists" in msg
        assert session.examine("you", "note.txt") == "v1"

    def test_create_then_take(self, session: WorldSession) -> None:
        session.create("you", "book.txt", "Once upon a time...")
        assert "Taken" in session.take("you", "book.txt")
        assert "book.txt" in session.inventory("you")
