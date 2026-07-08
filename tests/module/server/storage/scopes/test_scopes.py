from __future__ import annotations

from mars.server.storage.scopes.scope import DomainContribution, Problem, Scope, Solution
from mars.server.storage.scopes.store import ScopeStore


def test_scope_store_loads_hierarchy(tmp_path):
    store = ScopeStore(tmp_path)
    store.write("S1", "# Parent")
    store.write("S1.1", "# Child", parent_id="S1")

    scopes = {scope.id: scope for scope in store.load_all()}
    assert scopes["S1"].parent_id is None
    assert scopes["S1.1"].parent_id == "S1"
    assert scopes["S1.1"].path == "S1/S1.1.md"


def test_scope_is_static_domain_definition():
    sc = Scope(id="M1", title="Mathematics", document="# M1", path="math/M1.md")
    assert not hasattr(sc, "status")
    assert not hasattr(sc, "agents")
    assert not hasattr(sc, "solutions")


def test_problem_lifecycle():
    p = Problem(id="PR1", title="Riemann Hypothesis", description="Prove RH")
    assert p.status == "open"
    p.status = "in_progress"
    assert p.status in Problem.VALID_STATUSES


def test_problem_spans_multiple_scopes():
    p = Problem(
        id="PR1",
        title="Climate-Energy nexus",
        description="Model feedback between climate and energy systems",
        scope_ids=["C1", "E1", "EC1"],
    )
    assert "C1" in p.scope_ids
    assert "E1" in p.scope_ids
    assert "EC1" in p.scope_ids


def test_solution_is_subdivided_into_contributions():
    p = Problem(id="PR1", title="T", description="D")
    assert p.solution is None

    c1 = p.add_contribution(agent_id="climate-agent", domain_id="C1", content="Climate analysis")
    c2 = p.add_contribution(agent_id="energy-agent", domain_id="E1", content="Energy model")

    assert p.solution is not None
    assert p.solution.is_complete
    assert len(p.solution.contributions) == 2
    assert p.solution.contributions[0].domain_id == "C1"
    assert p.solution.contributions[1].domain_id == "E1"
    assert isinstance(c1, DomainContribution)
    assert isinstance(c2, DomainContribution)


def test_domain_contribution_fields():
    c = DomainContribution(agent_id="math-agent", domain_id="M1", content="Proof sketch")
    assert c.agent_id == "math-agent"
    assert c.domain_id == "M1"
    assert c.artifact_id is None


def test_solution_accumulates_contributions():
    sol = Solution(problem_id="PR1")
    assert not sol.is_complete
    sol.add(DomainContribution(agent_id="a1", domain_id="C1", content="x"))
    assert sol.is_complete
    assert len(sol.contributions) == 1


def test_scope_store_extracts_required_skills(tmp_path):
    doc = "# Test\n\n## Agent Skills Needed\n\n`physics`, `symbolic-math`, `numerics`\n"
    store = ScopeStore(tmp_path)
    store.write("T1", doc)
    scopes = {s.id: s for s in store.load_all()}
    assert scopes["T1"].required_skills == ["physics", "symbolic-math", "numerics"]
