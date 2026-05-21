# Contributing to MARS

Thank you for your interest in MARS!  
This guide covers everything you need to open a high-quality pull request.

---

## Table of contents

1. [Getting started](#getting-started)
2. [Project layout](#project-layout)
3. [Development workflow](#development-workflow)
4. [Coding conventions](#coding-conventions)
5. [Adding a provider](#adding-a-provider)
6. [Writing tests](#writing-tests)
7. [Opening a pull request](#opening-a-pull-request)
8. [Research grounding](#research-grounding)

---

## Getting started

```bash
git clone https://github.com/McNopper/MARS
cd MARS

# Install in editable mode with all dev dependencies
pip install -e ".[dev]"

# Copy the env template and fill in any API keys you want to test with
cp .env.example .env
```

Run the test suite before making any changes to confirm a clean baseline:

```bash
python -m pytest tests/ -v
```

---

## 📁 Project layout

```
mars/
  constants.py          Central registry of all magic values (strings, numbers, timeouts)
  runtime/
    server/             Headless TCP server: main.py, mcp_adapter.py, REST/WebSocket endpoints
    agents/             Built-in MCP service agents (clock, math, file, url, …) + agents.ini
    services/           Agent infrastructure: llm_wire_agent.py, registry.py, mcp_server.py, service_utils.py
  client/
    cli/                Rich four-pane TUI: main.py, client.py, models.py, commands.py, renderer.py, …
    providers/          LLM provider adapters: mock, anthropic, copilot, ollama, base, registry
  storage/
    artifacts/          Text and zip artifact store
    scopes/             Scope and ScopeStore — markdown-based domain knowledge arenas
tests/
  unit/                 Pure-Python unit tests, mirroring mars/ sub-tree
    runtime/server/     Unit tests for server internals
    runtime/agents/     Unit tests for individual agent tool functions
    runtime/services/   Unit tests for mcp_server, service_utils, registry, llm_wire_agent
    client/cli/         Unit tests for CLI models, utilities, rendering
    client/providers/   Unit tests for provider logic (mock, anthropic, openai_compat, …)
    storage/            Unit tests for artifacts and scopes
  component/            Single-component tests with lightweight fakes
  module/               Multi-component integration tests, mirroring mars/ sub-tree
  system/               End-to-end tests: real TCP server, real subprocesses, real wire agents
papers/                 Original research papers tracked via Git LFS
```

---

## Development workflow

1. **Create a branch** from `main`:
   ```bash
   git checkout -b my-feature
   ```
2. **Make your changes** — see [Coding conventions](#coding-conventions) below.
3. **Add or update tests** — every new behaviour needs a test.
4. **Run the full suite** and confirm nothing is broken:
   ```bash
   python -m pytest tests/ -v
   ```
5. **Commit** with a clear subject line (imperative mood, ≤72 chars):
   ```
   Add CohereProvider streaming support
   Fix MessageBus deadlock when fan-out target is offline
   ```
6. **Push** and open a pull request against `main`.

---

## Coding conventions

### Python style

- Python **3.11+**; use `from __future__ import annotations` at the top of every module.
- Type-annotate all function signatures and class attributes.
- Use `dataclasses.dataclass` or `pydantic.BaseModel` for structured data — not plain dicts.
- Prefer `async def` / `await` throughout; avoid blocking calls in async code.
- Keep modules focused: one public concept per file where practical.

### Imports

- Standard library → third-party → internal (`mars.*`) — one blank line between groups.
- Import canonical types from `mars.client.providers.base` (e.g. `LLMMessage`, `ToolSpec`).

### Comments and docstrings

- Module-level docstring explaining purpose and basic usage.
- Comment only non-obvious logic; do not narrate what the code already says clearly.

### Logging and errors

- Use `logging.getLogger(__name__)` — never `print()` in library code.
- Raise `ValueError` for invalid configuration; `RuntimeError` for unrecoverable state.

---

## Adding a provider

All providers live in `mars/client/providers/` and extend `LLMProvider` from `mars.client.providers.base`.

1. **Create** `mars/client/providers/myprovider.py`:

```python
from __future__ import annotations

from mars.client.providers.base import LLMMessage, LLMProvider, LLMResponse, ModelInfo


class MyProvider(LLMProvider):
    def __init__(self, *, model: str = "my-model-v1", api_key: str | None = None, **kwargs):
        import os
        self._model = model
        self._api_key = api_key or os.getenv("MY_API_KEY") or ""
        # initialise SDK client here

    async def complete(self, messages: list[LLMMessage], **kwargs) -> LLMResponse:
        # call SDK, return LLMResponse
        ...

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="my-model-v1", name="My Model v1")]
```

2. **Register** it in `mars/client/providers/registry.py`:

```python
"myprovider": ("mars.client.providers.myprovider", "MyProvider"),
```

3. **Add tests** in `tests/module/client/providers/test_providers.py`.

4. If the SDK needs an optional install, add an entry to `[project.optional-dependencies]` in `pyproject.toml`.

---

## Writing tests

Tests use **pytest** with `asyncio_mode = "auto"` (every `async def test_*` runs automatically).

### Test tiers

| Tier | Directory | Rules |
|------|-----------|-------|
| **unit** | `tests/unit/` | Pure Python — no I/O, no network, no subprocess. Instant. |
| **component** | `tests/component/` | Single component with lightweight fakes/mocks. |
| **module** | `tests/module/` | Multi-component integration (providers, registry, MCP adapter). |
| **system** | `tests/system/` | End-to-end: real TCP server, real subprocesses, real wire agents. |

All tiers run together with `python -m pytest tests/ -x -q`.

### Conventions

- Test files mirror the source tree: `tests/unit/runtime/services/test_registry.py` covers `mars/runtime/services/registry.py`.
- Group related tests in classes (`class TestMyFeature:`, `class TestSomething:`, …).
- Use `@pytest.mark.asyncio` only if your project version requires it — current config sets `asyncio_mode = "auto"`.
- Name tests descriptively: `test_scope_store_finds_by_skill`, not `test_scope_1`.
- Always clean up resources; use try/finally or pytest fixtures for teardown.

### Minimal async test example

```python
import pytest
from mars.client.providers.mock import MockProvider

class TestMyFeature:
    async def test_something(self):
        provider = MockProvider()
        response = await provider.complete([{"role": "user", "content": "Hello"}])
        assert response.content
```

### Mocking LLM calls

Use `MockProvider` (no API key, no network) for all unit and integration tests.  
Only use real providers in manually-run smoke tests; do not commit tests that require live API keys.

---

## Opening a pull request

- **One concern per PR** — separate refactors, features, and fixes.
- Fill in the PR description: *what* changed, *why*, and how you *verified* it.
- The PR must pass `python -m pytest tests/ -v` with no failures.
- Link any related issue in the description (`Closes #42`).
- If your change adds a new public API, update `README.md` or `BUILD.md` accordingly.

---

## Research grounding

MARS is explicitly grounded in academic research. If your contribution introduces a new concept or algorithm, consider:

- Citing the paper or textbook that defines it (add to `README.md` § References).
- Explaining the design choice in a module docstring (not just inline comments).
- For significant new subsystems, a short note in the PR description explaining the theoretical background is welcome.

Key references already used:

| Concept | Source |
|---------|--------|
| Agent lifecycle FSM | LARS (Nopper, 2000) |
| Sensor-to-agent middleware | EMIKA (Müller, Eymann, Nopper et al., 2004) |
| Game-theory strategies | Axelrod (1984); Shoham & Leyton-Brown (2009) |
| Federated discovery | Nopper & Kammerer (2000) |
