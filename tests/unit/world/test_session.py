"""Unit tests for WorldSession - presence and the verb surface over a World."""
from __future__ import annotations

from pathlib import Path

import pytest

from mars.world.world import World
from mars.world.server import WorldSession


@pytest.fixture()
def session(tmp_path: Path):
    w = World(tmp_path / "world")
    w.init()  # seeds only lobby
    w.create_room("library", "The Library", "A second room for isolation tests.")  # dynamic
    s = WorldSession(w, talk_ttl=0, presence_ttl=0)  # TTLs off so tests don't race the pruner
    yield s
    s.shutdown()


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


class TestProtocolThroughSession:
    def test_write_read_append(self, session: WorldSession) -> None:
        session.go("you", "library")
        assert "Protocol written" in session.write("you", "the rules")
        assert session.read("you") == "the rules"
        assert "Protocol updated" in session.append("you", "rule 2")
        assert "the rules" in session.read("you")
        assert "rule 2" in session.read("you")

    def test_protocol_is_per_room(self, session: WorldSession) -> None:
        session.write("you", "lobby deal")  # default room is lobby
        session.go("you", "library")
        assert session.read("you") == "(no protocol yet — write one)"
        session.go("you", "lobby")
        assert session.read("you") == "lobby deal"

    def test_look_hints_at_protocol(self, session: WorldSession) -> None:
        session.write("you", "1. first\n2. second")
        assert "Protocol: 2 line(s)" in session.look("you")

    def test_write_rejects_separator_friendlily(self, session: WorldSession) -> None:
        msg = session.write("you", "above\n\n---\n\nbelow")
        assert "Could not write" in msg

    def test_append_to_empty(self, session: WorldSession) -> None:
        assert "Protocol updated" in session.append("you", "just this")
        assert session.read("you") == "just this"


def test_rooms_lists_all(session: WorldSession) -> None:
    assert "lobby" in session.rooms()
    assert "library" in session.rooms()


@pytest.mark.slow
def test_idle_avatar_is_reaped(tmp_path: Path) -> None:
    import time
    w = World(tmp_path / "world")
    w.init()
    s = WorldSession(w, talk_ttl=0, presence_ttl=1.0)
    try:
        s.go("wanderer", "lobby")
        assert "wanderer" in s.look("explorer")
        time.sleep(2.5)  # TTL 1s + prune tick
        assert "wanderer" not in s.look("explorer")  # assumed gone
    finally:
        s.shutdown()


@pytest.mark.slow
def test_active_avatar_stays(tmp_path: Path) -> None:
    import time
    w = World(tmp_path / "world")
    w.init()
    s = WorldSession(w, talk_ttl=0, presence_ttl=1.0)
    try:
        s.say("chatty", "hello")
        for _ in range(3):
            time.sleep(0.5)
            s.say("chatty", "still here")  # implicit heartbeat within TTL
        assert "chatty" in s.look("explorer")
    finally:
        s.shutdown()


class TestAuthoring:
    def test_create_room_via_session(self, session: WorldSession) -> None:
        msg = session.create_room("you", "garden", "The Garden\nA quiet green space.")
        assert "Built room" in msg
        assert "Garden" in session.go("you", "garden")

    def test_create_room_rejects_duplicate(self, session: WorldSession) -> None:
        msg = session.create_room("you", "lobby", "Dup\nDesc.")
        assert "Could not build" in msg

    def test_create_room_rejects_empty_title(self, session: WorldSession) -> None:
        msg = session.create_room("you", "void", "   ")  # blank title after strip
        assert "Could not build" in msg


def test_dead_worker_thread_fails_fast(tmp_path: Path) -> None:
    """If the worker thread has died, verbs fail immediately instead of hanging for 30s."""
    w = World(tmp_path / "world")
    w.init()
    s = WorldSession(w, talk_ttl=0, presence_ttl=0)
    s.shutdown()
    assert not s._thread.is_alive()
    with pytest.raises(RuntimeError, match="worker thread is dead"):
        s.look("you")
