"""In-process ArtifactStore for MARS inter-agent artifact exchange."""

from __future__ import annotations

import asyncio
import logging
import weakref
from typing import Any, Callable

from mars.artifacts.artifact import Artifact

logger = logging.getLogger(__name__)


class _ObserverRef:
    """Weak-reference wrapper for put observers."""

    def __init__(self, callback: Callable[[Artifact], None]) -> None:
        self._callback = callback
        try:
            self._ref: weakref.ReferenceType[Callable[[Artifact], None]] = weakref.WeakMethod(callback)  # type: ignore[arg-type]
        except TypeError:
            self._ref = weakref.ref(callback)

    def resolve(self) -> Callable[[Artifact], None] | None:
        """Return the live callback, or ``None`` if it has been collected."""
        return self._ref()

    def matches(self, callback: Callable[[Artifact], None]) -> bool:
        """Return ``True`` when this reference points at *callback*."""
        return self.resolve() is callback


class ArtifactStore:
    """Shared in-process store for artifacts exchanged between agents.

    The store is attached to the Platform and is accessible from every agent
    via ``self._artifact_store``. Artifact IDs are referenced in
    ``Message.attachments``; receivers fetch the payload on demand.

    Put observers are kept via weak references when possible so bound-method
    callbacks do not keep agent instances alive after shutdown.

    Thread safety: all public methods are async and safe to call from
    concurrent asyncio tasks (the internal dict is protected by a lock).
    """

    def __init__(self) -> None:
        self._store: dict[str, Artifact] = {}
        self._lock = asyncio.Lock()
        self._put_observers: list[_ObserverRef] = []

    def add_put_observer(self, callback: Callable[[Artifact], None]) -> None:
        """Register a callback invoked after every artifact is stored."""
        if any(ref.matches(callback) for ref in self._put_observers):
            return
        self._put_observers.append(_ObserverRef(callback))

    def remove_put_observer(self, callback: Callable[[Artifact], None]) -> None:
        """Unregister a previously added observer (no-op if not found)."""
        self._put_observers = [
            ref for ref in self._put_observers if not ref.matches(callback)
        ]

    def _live_put_observers(self) -> list[Callable[[Artifact], None]]:
        """Return live callbacks and prune dead weak references."""
        live: list[Callable[[Artifact], None]] = []
        remaining: list[_ObserverRef] = []
        for ref in self._put_observers:
            callback = ref.resolve()
            if callback is None:
                continue
            live.append(callback)
            remaining.append(ref)
        self._put_observers = remaining
        return live

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    async def put(self, artifact: Artifact) -> str:
        """Store an artifact and return its ID.

        If an artifact with the same ID already exists it is overwritten.
        """
        async with self._lock:
            self._store[artifact.artifact_id] = artifact
        logger.debug(
            "ArtifactStore: stored %s (%s, %s)",
            artifact.artifact_id[:8],
            artifact.name,
            artifact.size_human,
        )
        for callback in self._live_put_observers():
            try:
                callback(artifact)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "ArtifactStore observer failed for %s",
                    artifact.artifact_id,
                )
        return artifact.artifact_id

    async def get(self, artifact_id: str) -> Artifact | None:
        """Fetch an artifact by ID. Returns ``None`` if not found."""
        async with self._lock:
            return self._store.get(artifact_id)

    async def delete(self, artifact_id: str) -> bool:
        """Remove an artifact. Returns ``True`` if it existed."""
        async with self._lock:
            existed = artifact_id in self._store
            self._store.pop(artifact_id, None)
        if existed:
            logger.debug("ArtifactStore: deleted %s", artifact_id[:8])
        return existed

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_all(self) -> list[Artifact]:
        """Return all stored artifacts."""
        async with self._lock:
            return list(self._store.values())

    async def list_artifacts(self) -> list[Artifact]:
        """Alias for :meth:`list_all` for API readability."""
        return await self.list_all()

    async def list_by_creator(self, agent_id: str) -> list[Artifact]:
        """Return all artifacts created by a specific agent."""
        async with self._lock:
            return [a for a in self._store.values() if a.created_by == agent_id]

    async def list_summaries(self, creator: str | None = None) -> list[dict[str, Any]]:
        """Return JSON-serialisable summaries (no binary data).

        Parameters
        ----------
        creator:
            Filter by creator agent ID. Pass ``None`` for all artifacts.
        """
        items = await self.list_by_creator(creator) if creator else await self.list_all()
        return [a.summary() for a in items]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def size(self) -> int:
        """Return the number of stored artifacts."""
        async with self._lock:
            return len(self._store)

    def __repr__(self) -> str:
        return f"ArtifactStore(count={len(self._store)})"
