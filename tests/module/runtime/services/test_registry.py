from mars.runtime.services.registry import AGENT_REGISTRY, get, all_specs, AgentSpec


def test_registry_has_built_in_agents():
    assert "clock" in AGENT_REGISTRY
    assert "profiler" in AGENT_REGISTRY
    assert "status" in AGENT_REGISTRY


def test_get_returns_spec():
    spec = get("clock")
    assert spec is not None
    assert isinstance(spec, AgentSpec)
    assert "clock" in spec.skills
    assert spec.protocol == "mcp"


def test_get_unknown_returns_none():
    assert get("nonexistent") is None


def test_all_specs_returns_list():
    specs = all_specs()
    assert len(specs) >= 3
    names = [s.name for s in specs]
    assert "clock" in names
    assert "profiler" in names
    assert "status" in names


def test_each_spec_has_required_fields():
    for spec in all_specs():
        assert spec.name
        assert spec.description
        assert spec.command
        assert isinstance(spec.skills, list)


def test_command_substitution():
    spec = get("clock")
    # MCP agents may have {workdir} but not {server}
    cmd = spec.command.format(server="localhost:7432", workdir="artifacts/clock")
    assert spec.command  # command is present


def test_cost_field_defaults_to_free():
    spec = get("clock")
    assert spec.cost == "free"


def test_free_agents():
    free = [s for s in all_specs() if s.cost == "free"]
    assert len(free) >= 3  # clock, profiler, status all free


def test_mcp_agents_have_protocol_field():
    """All built-in service agents should have protocol=mcp."""
    for name in ("clock", "profiler", "status", "sympy", "scipy"):
        spec = get(name)
        assert spec is not None
        assert spec.protocol == "mcp", f"{name} should be mcp, got {spec.protocol}"
