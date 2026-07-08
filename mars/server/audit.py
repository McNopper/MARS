"""Append-only JSON-lines audit log for server events."""
from __future__ import annotations

import contextlib
import json
import os
import stat
from datetime import datetime
from typing import Any


class MARSAuditLog:
    """Append-only JSON-lines audit log.

    Two tiers of detail:

    * **Structural** (always on): spawn/despawn/feed events from ``state._fire``.
      These record which agents are active and the snippet of every message.

    * **Full protocol** (``verbose=True``): every bilateral wire frame —
      complete message text, tool calls, tool results.  Enable with
      ``--audit-verbose`` on ``python -m mars.server.main``.
    """

    def __init__(self, path: str = "mars_audit.jsonl", verbose: bool = False) -> None:
        self._path = path
        self._verbose = verbose
        self._fh = open(path, "a", encoding="utf-8")  # noqa: SIM115
        with contextlib.suppress(OSError, NotImplementedError):
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    @property
    def verbose(self) -> bool:
        return self._verbose

    def log(self, event: dict[str, Any]) -> None:
        """Log a structural event (always written regardless of verbose flag)."""
        payload = {"ts": datetime.now().isoformat(), **event}
        self._fh.write(json.dumps(payload, default=str) + "\n")
        self._fh.flush()

    def log_msg(self, t: str, **fields: Any) -> None:
        """Log a full wire-protocol frame.  Only written when ``verbose=True``."""
        if not self._verbose:
            return
        payload = {"ts": datetime.now().isoformat(), "t": t, **fields}
        self._fh.write(json.dumps(payload, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._fh.flush()
        with contextlib.suppress(Exception):
            self._fh.close()

    def __enter__(self) -> MARSAuditLog:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
