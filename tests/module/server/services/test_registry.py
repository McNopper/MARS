from mars.server.services.registry import get_service, list_services, get_service_info, service_info


def test_registry_has_built_in_agents():
    services = list_services()
    assert "status" in services
    assert "launcher" in services


def test_get_returns_spec():
    """Test that get_service returns a Service instance."""
    service = get_service("status")
    assert service is not None
    assert service.service_id == "status"


def test_get_unknown_raises_error():
    """Test that get_service raises ValueError for unknown services."""
    try:
        get_service("nonexistent")
        assert False, "Expected ValueError"
    except ValueError:
        pass  # Expected


def test_list_services_returns_list():
    services = list_services()
    assert len(services) >= 4  # discovery, status, launcher, cli
    assert "status" in services
    assert "launcher" in services
    assert "discovery" in services


def test_each_service_has_required_fields():
    """Test that all services have proper metadata."""
    for info in service_info():
        assert info["name"]
        assert info["type"] in ["llm", "mcp", "a2a", "builtin"]
        assert info["module"]


def test_get_service_info():
    """Test get_service_info returns proper metadata."""
    info = get_service_info("status")
    assert info is not None
    assert info["name"] == "status"
    assert info["type"] == "builtin"
    assert info["default"] is True


def test_get_service_info_unknown_returns_none():
    """Test get_service_info returns None for unknown services."""
    info = get_service_info("nonexistent")
    assert info is None


def test_default_services():
    """Test that expected services are marked as default."""
    from mars.server.services.registry import DEFAULT_SERVICES
    assert "discovery" in DEFAULT_SERVICES
    assert "status" in DEFAULT_SERVICES
    assert "launcher" in DEFAULT_SERVICES
    assert "cli" in DEFAULT_SERVICES


def test_free_services():
    """Test that free services are properly marked."""
    from mars.server.services.registry import FREE_SERVICES
    assert "ollama" in FREE_SERVICES
    assert "mock" not in FREE_SERVICES      # test-only, not in FREE_SERVICES
    assert "mock-tool" not in FREE_SERVICES  # test-only, not in FREE_SERVICES
