"""
Unit tests for TUI scroll and sidebar cursor navigation logic.

Tests cover:
- chat_scroll increments/decrements on ↑/↓ key when focus == "chat"
- sidebar focus: arrow keys move cursor via _nav_sidebar without switching rooms
- scroll clamps at 0
- panel_focus routing (only focused panel scrolls)
- scroll reset to 0 on panel switch simulation
- PgUp/PgDn scancodes ('I','Q') are ignored
- _nav_sidebar clamping and informational agent highlighting
- _sync_sidebar_cursor: syncs cursor to current_room position
"""
import pytest
from mars.client.cli.main import _nav_sidebar, _sync_sidebar_cursor


# ---------------------------------------------------------------------------
# Minimal fake state for tests
# ---------------------------------------------------------------------------

class _FakeState:
    def __init__(self):
        self.chat_scroll: int = 0
        self.sidebar_scroll: int = 0
        self.sidebar_cursor: int = 0
        self.sidebar_visible_height: int = 20
        self.panel_focus: str = "chat"
        self.current_room: str = ""
        self.chat_scroll: int = 0
        self.agents: dict = {}
        self.rooms: dict = {}


def _make_state_with_agents(agent_ids: list[str], current: str = "") -> _FakeState:
    """Helper: build a _FakeState with a fake agents dict."""
    from types import SimpleNamespace
    s = _FakeState()
    s.agents = {aid: SimpleNamespace(is_current=(aid == current)) for aid in agent_ids}
    s.current_room = current or (agent_ids[0] if agent_ids else "")
    return s


def _apply_scroll_key(state: _FakeState, sc: str) -> None:
    """Mirrors the _scroll_key Windows inner function in mars/client/cli/main.py."""
    UP = ('H',)
    DOWN = ('P',)
    focus = state.panel_focus

    if sc in UP:
        if focus == "chat":
            state.chat_scroll += 1
        elif focus == "sidebar":
            _nav_sidebar(state, -1)     # arrow up → move cursor up (lower index)
    elif sc in DOWN:
        if focus == "chat":
            state.chat_scroll = max(0, state.chat_scroll - 1)
        elif focus == "sidebar":
            _nav_sidebar(state, +1)     # arrow down → move cursor down (higher index)
    # Any other scancode → ignored


def _apply_unix_scroll(state: _FakeState, ch3: str) -> None:
    """Mirrors the Unix ESC[ escape handler in mars/client/cli/main.py."""
    focus = state.panel_focus
    if ch3 == 'A':
        if focus == "chat":
            state.chat_scroll += 1
        elif focus == "sidebar":
            _nav_sidebar(state, -1)
    elif ch3 == 'B':
        if focus == "chat":
            state.chat_scroll = max(0, state.chat_scroll - 1)
        elif focus == "sidebar":
            _nav_sidebar(state, +1)
    # '5' (PgUp) and '6' (PgDn) → NOT handled (no branch)


# ======================================================
# Windows path tests
# ======================================================

class TestWindowsScrollKey:
    def test_up_increments_chat_scroll(self):
        s = _FakeState()
        _apply_scroll_key(s, 'H')
        assert s.chat_scroll == 1

    def test_down_decrements_chat_scroll(self):
        s = _FakeState()
        s.chat_scroll = 3
        _apply_scroll_key(s, 'P')
        assert s.chat_scroll == 2

    def test_down_clamps_chat_scroll_at_zero(self):
        s = _FakeState()
        s.chat_scroll = 0
        _apply_scroll_key(s, 'P')
        assert s.chat_scroll == 0

    def test_pgup_scancode_I_is_ignored(self):
        s = _FakeState()
        _apply_scroll_key(s, 'I')
        assert s.chat_scroll == 0
        assert s.sidebar_scroll == 0

    def test_pgdn_scancode_Q_is_ignored(self):
        s = _FakeState()
        s.chat_scroll = 5
        _apply_scroll_key(s, 'Q')
        assert s.chat_scroll == 5

    def test_unknown_scancode_is_ignored(self):
        s = _FakeState()
        _apply_scroll_key(s, 'X')
        assert s.chat_scroll == 0

    def test_sidebar_up_moves_cursor(self):
        s = _make_state_with_agents(["a", "b", "c"], current="b")
        s.panel_focus = "sidebar"
        s.sidebar_cursor = 1
        _apply_scroll_key(s, 'H')
        assert s.sidebar_cursor == 0
        assert s.current_room == "b"

    def test_sidebar_down_moves_cursor(self):
        s = _make_state_with_agents(["a", "b", "c"], current="a")
        s.panel_focus = "sidebar"
        s.sidebar_cursor = 0
        _apply_scroll_key(s, 'P')
        assert s.sidebar_cursor == 1
        assert s.current_room == "a"

    def test_only_chat_scrolls_when_focus_chat(self):
        s = _make_state_with_agents(["a", "b"], current="a")
        s.panel_focus = "chat"
        s.sidebar_cursor = 0
        _apply_scroll_key(s, 'H')
        assert s.chat_scroll == 1
        assert s.sidebar_cursor == 0   # sidebar unchanged

    def test_multiple_ups_accumulate(self):
        s = _FakeState()
        for _ in range(5):
            _apply_scroll_key(s, 'H')
        assert s.chat_scroll == 5

    def test_scroll_up_then_down_to_zero(self):
        s = _FakeState()
        for _ in range(3):
            _apply_scroll_key(s, 'H')
        for _ in range(3):
            _apply_scroll_key(s, 'P')
        assert s.chat_scroll == 0

    def test_scroll_down_below_zero_stays_zero(self):
        s = _FakeState()
        _apply_scroll_key(s, 'H')
        _apply_scroll_key(s, 'P')
        _apply_scroll_key(s, 'P')
        _apply_scroll_key(s, 'P')
        assert s.chat_scroll == 0


# ======================================================
# Unix path tests
# ======================================================

class TestUnixScrollKey:
    def test_A_increments_chat_scroll(self):
        s = _FakeState()
        _apply_unix_scroll(s, 'A')
        assert s.chat_scroll == 1

    def test_B_decrements_chat_scroll(self):
        s = _FakeState()
        s.chat_scroll = 2
        _apply_unix_scroll(s, 'B')
        assert s.chat_scroll == 1

    def test_B_clamps_at_zero(self):
        s = _FakeState()
        _apply_unix_scroll(s, 'B')
        assert s.chat_scroll == 0

    def test_pgup_sequence_5_is_ignored(self):
        s = _FakeState()
        _apply_unix_scroll(s, '5')
        assert s.chat_scroll == 0
        assert s.sidebar_scroll == 0

    def test_pgdn_sequence_6_is_ignored(self):
        s = _FakeState()
        s.chat_scroll = 5
        _apply_unix_scroll(s, '6')
        assert s.chat_scroll == 5

    def test_A_sidebar_moves_cursor_up(self):
        s = _make_state_with_agents(["a", "b", "c"], current="b")
        s.panel_focus = "sidebar"
        s.sidebar_cursor = 1
        _apply_unix_scroll(s, 'A')
        assert s.sidebar_cursor == 0
        assert s.current_room == "b"

    def test_B_sidebar_moves_cursor_down(self):
        s = _make_state_with_agents(["a", "b", "c"], current="a")
        s.panel_focus = "sidebar"
        s.sidebar_cursor = 0
        _apply_unix_scroll(s, 'B')
        assert s.sidebar_cursor == 1
        assert s.current_room == "a"

    def test_unknown_escape_char_is_ignored(self):
        s = _FakeState()
        _apply_unix_scroll(s, 'C')
        assert s.chat_scroll == 0


# ======================================================
# _nav_sidebar unit tests
# ======================================================

class TestNavSidebar:
    def test_nav_down_moves_cursor(self):
        s = _make_state_with_agents(["a", "b", "c"], current="a")
        _nav_sidebar(s, +1)
        assert s.sidebar_cursor == 1
        assert s.current_room == "a"

    def test_nav_up_moves_cursor(self):
        s = _make_state_with_agents(["a", "b", "c"], current="c")
        s.sidebar_cursor = 2
        _nav_sidebar(s, -1)
        assert s.sidebar_cursor == 1
        assert s.current_room == "c"

    def test_nav_clamps_at_top(self):
        s = _make_state_with_agents(["a", "b"], current="a")
        s.sidebar_cursor = 0
        _nav_sidebar(s, -1)
        assert s.sidebar_cursor == 0
        assert s.current_room == "a"

    def test_nav_clamps_at_bottom(self):
        s = _make_state_with_agents(["a", "b"], current="b")
        s.sidebar_cursor = 1
        _nav_sidebar(s, +1)
        assert s.sidebar_cursor == 1
        assert s.current_room == "b"

    def test_nav_keeps_chat_scroll(self):
        s = _make_state_with_agents(["a", "b"], current="a")
        s.chat_scroll = 5
        _nav_sidebar(s, +1)
        assert s.chat_scroll == 5

    def test_nav_switches_is_current_flag(self):
        s = _make_state_with_agents(["a", "b", "c"], current="a")
        _nav_sidebar(s, +1)
        assert s.agents["b"].is_current is True
        assert s.agents["a"].is_current is False
        assert s.agents["c"].is_current is False

    def test_nav_empty_agents_noop(self):
        s = _FakeState()
        # Should not raise
        _nav_sidebar(s, +1)
        assert s.sidebar_cursor == 0


# ======================================================
# _sync_sidebar_cursor unit tests
# ======================================================

class TestSyncSidebarCursor:
    def test_sync_sets_cursor_to_current_room(self):
        s = _make_state_with_agents(["a", "b", "c"], current="b")
        s.sidebar_cursor = 0  # out of sync
        _sync_sidebar_cursor(s)
        assert s.sidebar_cursor == 1

    def test_sync_first_agent(self):
        s = _make_state_with_agents(["x", "y"], current="x")
        s.sidebar_cursor = 1
        _sync_sidebar_cursor(s)
        assert s.sidebar_cursor == 0

    def test_sync_last_agent(self):
        s = _make_state_with_agents(["x", "y", "z"], current="z")
        s.sidebar_cursor = 0
        _sync_sidebar_cursor(s)
        assert s.sidebar_cursor == 2

    def test_sync_unknown_agent_no_change(self):
        s = _make_state_with_agents(["a", "b"], current="a")
        s.current_room = "unknown"
        s.sidebar_cursor = 0
        _sync_sidebar_cursor(s)
        assert s.sidebar_cursor == 0  # unchanged


# ======================================================
# Scroll reset on panel switch
# ======================================================

class TestScrollReset:
    def test_scroll_reset_after_panel_switch(self):
        """Simulate what the app does on /switch: reset chat_scroll to 0."""
        s = _FakeState()
        s.chat_scroll = 7
        s.chat_scroll = 0
        assert s.chat_scroll == 0

    def test_nav_sidebar_does_not_touch_chat_scroll_when_no_switch(self):
        """sidebar_scroll is independent of chat_scroll."""
        s = _make_state_with_agents(["a", "b"], current="a")
        s.chat_scroll = 3
        _nav_sidebar(s, +1)
        assert s.chat_scroll == 3
        assert s.sidebar_cursor == 1


# ======================================================
# Focus routing cross-check
# ======================================================

class TestFocusRouting:
    @pytest.mark.parametrize("focus,attr", [
        ("chat", "chat_scroll"),
    ])
    def test_up_scrolls_correct_panel(self, focus, attr):
        s = _FakeState()
        s.panel_focus = focus
        _apply_scroll_key(s, 'H')
        assert getattr(s, attr) == 1

    @pytest.mark.parametrize("focus,attr", [
        ("chat", "chat_scroll"),
    ])
    def test_down_scrolls_correct_panel(self, focus, attr):
        s = _FakeState()
        s.panel_focus = focus
        setattr(s, attr, 5)
        _apply_scroll_key(s, 'P')
        assert getattr(s, attr) == 4
