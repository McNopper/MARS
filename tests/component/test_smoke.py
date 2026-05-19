"""Smoke tests: import and initialise every top-level module that participates
in server *and* client startup.  These tests catch NameErrors, missing imports,
and broken module-level code *before* a human tries to start either process.

The pattern mirrors the failure that occurred with ``Path`` not being imported
in ``mars.srv.main`` — a bug that only surfaces at runtime when ``_async_server``
is called, not at import time.  Each test here exercises the relevant code path
in isolation so the CI suite catches it first.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path


# ---------------------------------------------------------------------------
# Import smoke tests — catch NameError / ImportError at module load time
# ---------------------------------------------------------------------------


def test_srv_main_imports():
    """mars.srv.main must import without errors."""
    module = importlib.import_module("mars.srv.main")
    assert module is not None


def test_cli_main_imports():
    """mars.cli.main must import without errors."""
    module = importlib.import_module("mars.cli.main")
    assert module is not None


def test_scope_store_imports():
    """mars.scopes.store must import without errors."""
    module = importlib.import_module("mars.scopes.store")
    assert module is not None


# ---------------------------------------------------------------------------
# Startup path smoke tests — catch NameErrors that only surface at call time
# ---------------------------------------------------------------------------


def test_scope_store_instantiation(tmp_path: Path):
    """ScopeStore(Path(...)) must not raise — this is the exact line that
    failed in mars.srv.main when ``Path`` was not imported."""
    from mars.scopes.store import ScopeStore

    store = ScopeStore(tmp_path)
    assert store is not None


def test_scope_store_load_all_empty(tmp_path: Path):
    """ScopeStore.load_all() on an empty directory must return an empty list
    without raising."""
    from mars.scopes.store import ScopeStore

    store = ScopeStore(tmp_path)
    scopes = store.load_all()
    assert isinstance(scopes, list)


def test_scope_store_load_all_real():
    """ScopeStore.load_all() on the real scopes/ directory must not raise,
    even when the directory is missing or empty."""
    from mars.scopes.store import ScopeStore

    store = ScopeStore(Path("scopes"))
    scopes = store.load_all()
    assert isinstance(scopes, list)


def test_mars_state_instantiation():
    """MARSState must be constructable without a live Platform."""
    from mars.cli.main import MARSState

    state = MARSState(platform_name="smoke-test")
    assert state is not None


def test_mars_state_scroll_fields():
    """MARSState must have scroll, cursor, and panel_focus fields for TUI scrolling."""
    from mars.cli.main import MARSState

    s = MARSState()
    assert s.panel_focus == "chat"
    assert s.chat_scroll == 0
    assert s.sidebar_scroll == 0
    assert s.sidebar_cursor == 0


def test_agent_record_instantiation():
    """AgentRecord must be constructable with required fields."""
    from mars.cli.main import AgentRecord

    rec = AgentRecord(
        agent_id="smoke-agent",
        agent_type="ServiceAgent",
        domain="test",
        platform="local",
        fsm_state="idle",
        avatar="🔧",
    )
    assert rec.agent_id == "smoke-agent"


def test_srv_main_has_path_import():
    """Verify that 'Path' is resolvable inside mars.srv.main — the specific
    symbol that was missing and caused the production server crash."""
    import mars.srv.main as srv_main

    # The module must expose Path via its globals (imported at module level)
    assert "Path" in vars(srv_main), (
        "mars.srv.main is missing 'from pathlib import Path' — "
        "server startup will crash at ScopeStore(Path('scopes'))"
    )


# ---------------------------------------------------------------------------
# Client smoke tests — mirror the server tests for the CLI client
# ---------------------------------------------------------------------------


def test_cli_main_has_default_port():
    """DEFAULT_PORT must be defined in mars.cli.main — used by _async_client."""
    cli_main = importlib.import_module("mars.cli.main")

    assert hasattr(cli_main, "DEFAULT_PORT"), (
        "mars.cli.main is missing DEFAULT_PORT — _async_client will crash"
    )
    assert isinstance(cli_main.DEFAULT_PORT, int)


def test_mars_client_terminal_instantiation():
    """MARSClientTerminal must be constructable with mock reader/writer/state —
    this is the first thing _async_client does after a successful TCP connect."""
    import asyncio
    from unittest.mock import MagicMock
    from mars.cli.main import MARSClientTerminal, MARSState, AgentRecord

    state = MARSState()
    state.agents["cli-user@1"] = AgentRecord(
        agent_id="cli-user@1",
        agent_type="HumanUser",
        domain="cli",
        platform="local",
        fsm_state="—",
        avatar="🧑",
    )

    reader = MagicMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)

    terminal = MARSClientTerminal(reader, writer, state, server_addr="localhost:7432")
    assert terminal is not None
    assert terminal._state is state
    assert terminal._server_addr == "localhost:7432"


def test_mars_client_terminal_apply_event_state():
    """MARSClientTerminal._apply_event must handle a 'state' event without
    crashing — this is called immediately after the server sends its initial
    state dump to the connecting client."""
    import asyncio
    from unittest.mock import MagicMock
    from mars.cli.main import MARSClientTerminal, MARSState

    state = MARSState()
    reader = MagicMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    terminal = MARSClientTerminal(reader, writer, state)

    terminal._apply_event({
        "t": "state",
        "platform_name": "mars-server",
        "agents": {
            "echo-md": {
                "agent_type": "EchoBot",
                "domain": "echo",
                "platform": "local",
                "fsm_state": "idle",
            }
        },
        "scopes": [],
        "problems": [],
    })

    assert state.platform_name == "mars-server"
    assert "echo-md" in state.agents


def test_mars_client_terminal_apply_event_spawn():
    """MARSClientTerminal._apply_event must handle a 'spawn' event."""
    import asyncio
    from unittest.mock import MagicMock
    from mars.cli.main import MARSClientTerminal, MARSState

    state = MARSState()
    reader = MagicMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    terminal = MARSClientTerminal(reader, writer, state)

    terminal._apply_event({
        "t": "spawn",
        "agent_id": "new-agent",
        "agent_type": "ServiceAgent",
        "domain": "test",
        "platform": "local",
        "fsm_state": "idle",
    })

    assert "new-agent" in state.agents


def test_mars_client_terminal_apply_event_despawn():
    """MARSClientTerminal._apply_event must handle a 'despawn' event."""
    import asyncio
    from unittest.mock import MagicMock
    from mars.cli.main import MARSClientTerminal, MARSState, AgentRecord

    state = MARSState()
    state.agents["temp-agent"] = AgentRecord(
        agent_id="temp-agent", agent_type="ServiceAgent",
        domain="test", platform="local",
        fsm_state="idle", avatar="🔧",
    )
    reader = MagicMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    terminal = MARSClientTerminal(reader, writer, state)

    terminal._apply_event({"t": "despawn", "agent_id": "temp-agent"})
    assert "temp-agent" not in state.agents


def test_cli_main_has_mars_client_terminal():
    """MARSClientTerminal must be exported from mars.cli.main."""
    cli_main = importlib.import_module("mars.cli.main")

    assert hasattr(cli_main, "MARSClientTerminal"), (
        "mars.cli.main is missing MARSClientTerminal class"
    )



def test_cli_main_renderer_instantiation():
    """MARSRenderer must be constructable from a fresh MARSState."""
    from mars.cli.main import MARSRenderer, MARSState

    state = MARSState()
    renderer = MARSRenderer(state)
    assert renderer is not None
