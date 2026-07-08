"""Root test configuration and shared fixtures.

Test tier contract
------------------
Tests are executed in strict tier order.  A failure in a lower tier stops the
run — there is no point exercising higher-level integration if the building
blocks are broken.

  unit        Pure isolation.  One class or function under test, all
              dependencies mocked.  No I/O, no network, no subprocesses.
              Must finish in milliseconds.

  component   A handful of units wired together inside the same process.
              No real network or subprocess I/O.  Checks that modules
              import cleanly and that cross-module wiring is correct.

  module      A complete feature tested end-to-end inside one process.
              May open real loopback TCP connections.  No external services.

  system      Full-stack tests that start real server subprocesses or call
              real external APIs (Ollama, Anthropic, …).  Slow by design.
              Heavy tests (LLM calls) are excluded from the default run.
"""
from __future__ import annotations

import os
import pathlib
import unicodedata
from io import StringIO
from typing import Optional

import socket

import pytest


# ---------------------------------------------------------------------------
# Port allocation fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def unused_tcp_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Snapshot helpers (used by renderer tests in unit/)
# ---------------------------------------------------------------------------

SNAPSHOTS_DIR = pathlib.Path(__file__).parent / "snapshots"
HTML_DIR = SNAPSHOTS_DIR / "html"
UPDATE = os.environ.get("UPDATE_SNAPSHOTS") == "1"


def _char_width(ch: str) -> int:
    try:
        import wcwidth
        w = wcwidth.wcwidth(ch)
        return max(1, w) if w >= 0 else 1
    except ImportError:
        eaw = unicodedata.east_asian_width(ch)
        return 2 if eaw in ("W", "F") else 1


def _normalise_to_fixed_width(text: str, placeholder: str = "?") -> str:
    """Replace every wide (2-cell) character with *placeholder* (1-cell)."""
    return "".join(
        placeholder if _char_width(ch) > 1 else ch
        for ch in text
    )


def render_to_text(renderable, *, width: int = 120, height: int = 40) -> str:
    """Render any Rich renderable to a fixed-width plain-text string."""
    from rich.console import Console
    buf = StringIO()
    console = Console(
        file=buf,
        record=True,
        force_terminal=True,
        safe_box=True,
        width=width,
        height=height,
        color_system=None,
        highlight=False,
    )
    console.print(renderable)
    return _normalise_to_fixed_width(buf.getvalue())


def render_to_html(renderable, *, width: int = 120, height: int = 40) -> str:
    """Render to HTML string (for human visual inspection)."""
    from rich.console import Console
    buf = StringIO()
    console = Console(
        file=buf,
        record=True,
        force_terminal=True,
        width=width,
        height=height,
        color_system="truecolor",
        highlight=False,
    )
    console.print(renderable)
    return console.export_html(inline_styles=True)


def assert_snapshot(name: str, content: str, *, save_html: Optional[str] = None) -> None:
    """Assert rendered content matches stored snapshot."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snap_file = SNAPSHOTS_DIR / f"{name}.txt"

    if UPDATE or not snap_file.exists():
        snap_file.write_text(content, encoding="utf-8")
        if save_html:
            HTML_DIR.mkdir(parents=True, exist_ok=True)
            (HTML_DIR / f"{name}.html").write_text(save_html, encoding="utf-8")
        return

    expected = snap_file.read_text(encoding="utf-8")
    assert content == expected, (
        f"\nSnapshot mismatch: {snap_file}\n"
        f"Run with UPDATE_SNAPSHOTS=1 to regenerate.\n\n"
        f"--- expected (first 20 lines) ---\n"
        + "\n".join(expected.splitlines()[:20])
        + "\n\n--- got (first 20 lines) ---\n"
        + "\n".join(content.splitlines()[:20])
    )


@pytest.fixture()
def snapshot(request):
    """Render a Rich renderable and assert against a named snapshot file."""
    def _assert(renderable, name: str | None = None, *, width: int = 120):
        snap_name = name or request.node.nodeid.replace("/", "_").replace("::", "__")
        text = render_to_text(renderable, width=width)
        html = render_to_html(renderable, width=width)
        assert_snapshot(snap_name, text, save_html=html)
    return _assert
