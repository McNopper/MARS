"""Root pytest configuration.

Automatically loads `.env` from the repository root (if present) before any
test module is imported.  This makes ``GITHUB_TOKEN``, ``ANTHROPIC_API_KEY``,
etc. available to skip-condition checks (e.g. ``_copilot_available()``) without
requiring python-dotenv as a dependency.
"""
from __future__ import annotations

import os
import pathlib


def _load_dotenv(path: pathlib.Path) -> None:
    """Parse a .env file and populate os.environ for any key not already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip optional surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# Load once at collection time — before any module-level skip conditions run.
_load_dotenv(pathlib.Path(__file__).parent / ".env")
