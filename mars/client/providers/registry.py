"""Provider registry – factory for MARS LLM provider adapters.

Usage
-----
    from mars.client.providers import get_provider, list_providers

    provider = get_provider("copilot")              # GitHub Copilot (gh auth login)
    provider = get_provider("ollama", model="llama3.2")
    provider = get_provider("anthropic")            # Anthropic Claude

    print(list_providers())
    # ['anthropic', 'copilot', 'mock', 'ollama']

Adding a new provider
---------------------
1. Create ``mars/client/providers/<name>.py`` with a class subclassing
   ``OpenAICompatibleProvider`` (for REST/OpenAI-compatible APIs)
   or ``LLMProvider`` (for non-OpenAI APIs).
2. Add an entry to ``REGISTRY`` below.

Provider kwargs are forwarded directly to the provider's ``__init__``.
Common kwargs: ``model``, ``api_key``, ``host`` (Ollama).
"""

from __future__ import annotations

import importlib
from typing import Any

from mars.client.providers.base import LLMProvider

# Registry: provider name → (module path, class name)
# Lazy imports – the module is only loaded when get_provider() is called.
REGISTRY: dict[str, tuple[str, str]] = {
    # GitHub Copilot Chat (uses GITHUB_TOKEN / gh auth login – no extra SDK)
    "copilot":   ("mars.client.providers.copilot",   "CopilotProvider"),
    # Anthropic Claude (pip install anthropic + ANTHROPIC_API_KEY)
    "anthropic": ("mars.client.providers.anthropic", "AnthropicProvider"),
    # Local Ollama server (https://ollama.com – no API key required)
    "ollama":    ("mars.client.providers.ollama",    "OllamaProvider"),
    # Mock provider – offline testing, no API key required
    "mock":      ("mars.client.providers.mock",      "MockProvider"),
    # Mock provider that emits tool calls – for service-tool round-trip tests
    "mock-tool": ("mars.client.providers.mock",      "ToolCallMockProvider"),
}

# Aliases
_ALIASES: dict[str, str] = {
    "claude": "anthropic",
}

# Free-tier providers (no API cost)
FREE_PROVIDERS: set[str] = {
    "mock",
    "mock-tool",
    "copilot",
    "ollama",
}


def get_provider(name: str, **kwargs: Any) -> LLMProvider:
    """Instantiate a provider by name.

    Parameters
    ----------
    name:
        Provider name (case-insensitive), e.g. ``"copilot"``, ``"ollama"``.
        Aliases are resolved automatically.
    **kwargs:
        Forwarded to the provider's ``__init__``.  Common ones:
        ``model``, ``api_key``, ``host``.

    Raises
    ------
    ValueError
        If the provider name is unknown.
    ImportError
        If a required SDK package is not installed.
    """
    key = name.lower().strip()
    key = _ALIASES.get(key, key)

    entry = REGISTRY.get(key)
    if entry is None:
        providers = ", ".join(sorted(REGISTRY))
        aliases = ", ".join(f"{alias}→{target}" for alias, target in sorted(_ALIASES.items()))
        raise ValueError(
            f"Unknown provider {name!r}. Available providers: {providers}. "
            f"Aliases: {aliases}"
        )

    module_path, class_name = entry
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(**kwargs)


def list_providers() -> list[str]:
    """Return sorted list of all registered provider names."""
    return sorted(REGISTRY)


def provider_info() -> list[dict[str, Any]]:
    """Return metadata about all providers for display in the CLI."""
    rows = []
    for name in sorted(REGISTRY):
        rows.append(
            {
                "name": name,
                "free": name in FREE_PROVIDERS,
                "local": name in {"ollama"},
                "module": REGISTRY[name][0],
            }
        )
    return rows
