"""Unit tests for ArtifactStore put observers."""
from __future__ import annotations

import asyncio

import pytest

from mars.storage.artifacts.artifact import Artifact
from mars.storage.artifacts.store import ArtifactStore


@pytest.mark.asyncio
async def test_observer_called_on_put() -> None:
    store = ArtifactStore()
    seen: list[Artifact] = []

    def observer(artifact: Artifact) -> None:
        seen.append(artifact)

    store.add_put_observer(observer)
    artifact = Artifact.from_text("result.txt", "hello", created_by="svc.test")

    artifact_id = await store.put(artifact)

    assert artifact_id == artifact.artifact_id
    assert seen == [artifact]


@pytest.mark.asyncio
async def test_multiple_observers_all_called() -> None:
    store = ArtifactStore()
    seen_one: list[str] = []
    seen_two: list[str] = []

    def observer_one(artifact: Artifact) -> None:
        seen_one.append(artifact.artifact_id)

    def observer_two(artifact: Artifact) -> None:
        seen_two.append(artifact.artifact_id)

    store.add_put_observer(observer_one)
    store.add_put_observer(observer_two)
    artifact = Artifact.from_text("result.txt", "hello")

    await store.put(artifact)

    assert seen_one == [artifact.artifact_id]
    assert seen_two == [artifact.artifact_id]


@pytest.mark.asyncio
async def test_remove_observer_stops_calls() -> None:
    store = ArtifactStore()
    seen: list[str] = []

    def observer(artifact: Artifact) -> None:
        seen.append(artifact.artifact_id)

    store.add_put_observer(observer)
    store.remove_put_observer(observer)

    await store.put(Artifact.from_text("result.txt", "hello"))

    assert seen == []


@pytest.mark.asyncio
async def test_observer_exception_does_not_break_put() -> None:
    store = ArtifactStore()

    def observer(_: Artifact) -> None:
        raise RuntimeError("boom")

    store.add_put_observer(observer)
    artifact = Artifact.from_text("result.txt", "hello")

    artifact_id = await store.put(artifact)

    assert artifact_id == artifact.artifact_id
    assert await store.get(artifact_id) is artifact


@pytest.mark.asyncio
async def test_observer_called_outside_lock() -> None:
    store = ArtifactStore()
    loop = asyncio.get_running_loop()
    observed = loop.create_future()

    def observer(artifact: Artifact) -> None:
        asyncio.get_running_loop()
        observed.set_result(artifact.artifact_id)

    store.add_put_observer(observer)
    artifact = Artifact.from_text("result.txt", "hello")

    await store.put(artifact)

    assert await asyncio.wait_for(observed, timeout=1.0) == artifact.artifact_id
