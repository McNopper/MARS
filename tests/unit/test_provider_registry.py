"""Unit tests for the provider registry — aliases, errors, listing."""
from __future__ import annotations

import pytest

from mars.providers.registry import (
    FREE_PROVIDERS,
    REGISTRY,
    get_provider,
    list_providers,
    provider_info,
)


def test_list_providers_returns_all_registered_names() -> None:
    providers = list_providers()
    assert isinstance(providers, list)
    assert "anthropic" in providers
    assert "ollama" in providers
    assert "mock" in providers
    assert "copilot" in providers


def test_list_providers_is_sorted() -> None:
    providers = list_providers()
    assert providers == sorted(providers)


def test_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("totally-unknown-provider-xyz")


def test_alias_claude_resolves_to_anthropic() -> None:
    """'claude' alias must resolve to the Anthropic provider (import may fail without key)."""
    from mars.providers.registry import _ALIASES
    assert _ALIASES.get("claude") == "anthropic"


def test_free_providers_set_is_correct() -> None:
    assert "mock" in FREE_PROVIDERS
    assert "ollama" in FREE_PROVIDERS
    assert "copilot" in FREE_PROVIDERS
    assert "anthropic" not in FREE_PROVIDERS


def test_provider_info_shape() -> None:
    rows = provider_info()
    assert isinstance(rows, list)
    assert len(rows) == len(REGISTRY)
    for row in rows:
        assert "name" in row
        assert "free" in row
        assert "local" in row
        assert "module" in row


def test_mock_provider_instantiates_without_key() -> None:
    provider = get_provider("mock")
    from mars.providers.mock import MockProvider
    assert isinstance(provider, MockProvider)


def test_mock_provider_with_response_kwarg() -> None:
    provider = get_provider("mock", response="hello from test")
    from mars.providers.mock import MockProvider
    assert isinstance(provider, MockProvider)
