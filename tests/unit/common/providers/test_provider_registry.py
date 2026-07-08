"""Unit tests for the provider registry — aliases, errors, listing."""
from __future__ import annotations

import pytest

from mars.server.services.registry import (
    FREE_SERVICES,
    REGISTRY,
    get_service,
    list_services,
    service_info,
)


def test_list_services_returns_all_registered_names() -> None:
    providers = list_services(include_test=True)
    assert isinstance(providers, list)
    assert "anthropic" in providers
    assert "ollama" in providers
    assert "mock" in providers
    assert "copilot" in providers


def test_list_services_is_sorted() -> None:
    providers = list_services()
    assert providers == sorted(providers)


def test_list_services_excludes_test_by_default() -> None:
    providers = list_services()
    assert "mock" not in providers
    assert "mock-tool" not in providers


def test_unknown_provider_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown service"):
        get_service("totally-unknown-provider-xyz")


def test_alias_claude_resolves_to_anthropic() -> None:
    """'claude' alias must resolve to the Anthropic provider (import may fail without key)."""
    from mars.server.services.registry import _ALIASES
    assert _ALIASES.get("claude") == "anthropic"


def test_free_providers_set_is_correct() -> None:
    assert "ollama" in FREE_SERVICES
    assert "copilot" in FREE_SERVICES
    assert "anthropic" not in FREE_SERVICES
    assert "mock" not in FREE_SERVICES  # test-only, removed from FREE_SERVICES


def test_service_info_shape() -> None:
    rows = service_info()
    assert isinstance(rows, list)
    non_test = sum(1 for e in REGISTRY.values() if not e[4])
    assert len(rows) == non_test
    for row in rows:
        assert "name" in row
        assert "free" in row
        assert "module" in row
        assert "available" in row


def test_mock_provider_instantiates_without_key() -> None:
    provider = get_service("mock")
    from mars.server.services.llm.mock import MockService
    assert isinstance(provider, MockService)


def test_mock_provider_with_response_kwarg() -> None:
    provider = get_service("mock", response="hello from test")
    from mars.server.services.llm.mock import MockService
    assert isinstance(provider, MockService)
