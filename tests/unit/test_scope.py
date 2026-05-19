"""Unit tests for mars.scopes.scope — pure data model, no I/O.

Test pyramid level: UNIT
Each test exercises exactly one class or one method in isolation.
No file system, no network, no platform required.

Grounded in:
- Smith (1980) Contract Net Protocol: Problem ↔ task announcement
- EMIKA (Müller et al. 2004): Solution subdivided into DomainContributions
- BDI (Rao & Georgeff 1995): Problem ↔ committed goal
"""
from __future__ import annotations

from datetime import datetime

import pytest

from mars.scopes.scope import DomainContribution, Problem, Scope, Solution


# ---------------------------------------------------------------------------
# Scope — static domain definition
# ---------------------------------------------------------------------------

class TestScope:
    def test_scope_has_required_fields(self):
        sc = Scope(id="M1", title="Mathematics", document="# M1", path="math/M1.md")
        assert sc.id == "M1"
        assert sc.title == "Mathematics"
        assert sc.path == "math/M1.md"
        assert sc.parent_id is None
        assert sc.required_skills == []

    def test_scope_with_parent(self):
        sc = Scope(id="M1.1", title="Algebra", document="# M1.1", path="math/M1/M1.1.md",
                   parent_id="M1")
        assert sc.parent_id == "M1"

    def test_scope_required_skills(self):
        sc = Scope(id="P1", title="Physics", document="", path="P1.md",
                   required_skills=["physics", "numerics"])
        assert "physics" in sc.required_skills
        assert "numerics" in sc.required_skills

    def test_scope_has_no_lifecycle_fields(self):
        """Scope is a static domain definition — no runtime lifecycle."""
        sc = Scope(id="C1", title="Climate", document="", path="C1.md")
        assert not hasattr(sc, "status")
        assert not hasattr(sc, "agents")
        assert not hasattr(sc, "solutions")
        assert not hasattr(sc, "created_at")

    def test_scope_children_property(self):
        """children is always an empty list — managed by ScopeStore."""
        sc = Scope(id="AI1", title="AI", document="", path="ai/AI1.md")
        assert sc.children == []


# ---------------------------------------------------------------------------
# DomainContribution — sub-solution from one agent in one domain
# ---------------------------------------------------------------------------

class TestDomainContribution:
    def test_basic_fields(self):
        c = DomainContribution(
            agent_id="climate-agent",
            domain_id="C1",
            content="Climate analysis result",
        )
        assert c.agent_id == "climate-agent"
        assert c.domain_id == "C1"
        assert c.content == "Climate analysis result"
        assert c.artifact_id is None

    def test_with_artifact(self):
        c = DomainContribution(
            agent_id="svc.ocr@1",
            domain_id="H1",
            content="extracted text",
            artifact_id="art-abc123",
        )
        assert c.artifact_id == "art-abc123"

    def test_timestamp_is_set(self):
        before = datetime.now()
        c = DomainContribution(agent_id="a", domain_id="X1", content="x")
        after = datetime.now()
        assert before <= c.ts <= after

    def test_domain_id_can_be_empty(self):
        """domain_id may be empty for cross-domain contributions not yet classified."""
        c = DomainContribution(agent_id="agent", domain_id="", content="result")
        assert c.domain_id == ""


# ---------------------------------------------------------------------------
# Solution — composite, subdivided into DomainContributions
# ---------------------------------------------------------------------------

class TestSolution:
    def test_empty_solution_is_incomplete(self):
        sol = Solution(problem_id="PR1")
        assert not sol.is_complete
        assert sol.contributions == []

    def test_add_makes_complete(self):
        sol = Solution(problem_id="PR1")
        sol.add(DomainContribution(agent_id="a", domain_id="C1", content="x"))
        assert sol.is_complete
        assert len(sol.contributions) == 1

    def test_multiple_contributions(self):
        sol = Solution(problem_id="PR2")
        sol.add(DomainContribution(agent_id="a1", domain_id="C1", content="climate"))
        sol.add(DomainContribution(agent_id="a2", domain_id="E1", content="energy"))
        sol.add(DomainContribution(agent_id="a3", domain_id="EC1", content="economics"))
        assert len(sol.contributions) == 3
        domain_ids = [c.domain_id for c in sol.contributions]
        assert "C1" in domain_ids
        assert "E1" in domain_ids
        assert "EC1" in domain_ids

    def test_contributions_are_ordered(self):
        """Contributions preserve insertion order."""
        sol = Solution(problem_id="PR3")
        for i, domain in enumerate(["M1", "P1", "CS1"]):
            sol.add(DomainContribution(agent_id=f"a{i}", domain_id=domain, content=f"c{i}"))
        assert [c.domain_id for c in sol.contributions] == ["M1", "P1", "CS1"]

    def test_summary_defaults_to_empty(self):
        sol = Solution(problem_id="PR1")
        assert sol.summary == ""

    def test_problem_id_is_preserved(self):
        sol = Solution(problem_id="PR42")
        assert sol.problem_id == "PR42"


# ---------------------------------------------------------------------------
# Problem — active challenge across one or more Scopes
# ---------------------------------------------------------------------------

class TestProblem:
    def test_required_fields(self):
        p = Problem(id="PR1", title="Riemann Hypothesis",
                    description="Prove or disprove the Riemann Hypothesis")
        assert p.id == "PR1"
        assert p.title == "Riemann Hypothesis"
        assert p.description == "Prove or disprove the Riemann Hypothesis"

    def test_default_status_is_open(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.status == "open"

    def test_valid_statuses(self):
        assert Problem.VALID_STATUSES == {"open", "assigned", "in_progress", "solved", "closed"}

    def test_all_lifecycle_transitions(self):
        p = Problem(id="PR1", title="T", description="D")
        for status in ("assigned", "in_progress", "solved", "closed"):
            p.status = status
            assert p.status in Problem.VALID_STATUSES

    def test_default_scope_ids_empty(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.scope_ids == []

    def test_spans_multiple_scopes(self):
        """A Problem can span multiple domain Scopes — cross-domain challenge."""
        p = Problem(
            id="PR1",
            title="Climate-Energy nexus",
            description="Model feedback loops between climate and energy systems",
            scope_ids=["C1", "E1", "EC1", "PL1"],
        )
        assert len(p.scope_ids) == 4
        assert "C1" in p.scope_ids

    def test_default_solution_is_none(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.solution is None

    def test_default_agents_empty(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.agents == []

    def test_default_priority_zero(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.priority == 0

    def test_priority_levels(self):
        for priority in (0, 1, 2):
            p = Problem(id="PR1", title="T", description="D", priority=priority)
            assert p.priority == priority

    def test_deadline_optional(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.deadline is None
        p2 = Problem(id="PR2", title="T", description="D", deadline="2025-12-31T23:59:59")
        assert p2.deadline == "2025-12-31T23:59:59"

    def test_created_at_is_set(self):
        before = datetime.now()
        p = Problem(id="PR1", title="T", description="D")
        after = datetime.now()
        assert before <= p.created_at <= after


class TestProblemAddContribution:
    def test_first_contribution_creates_solution(self):
        p = Problem(id="PR1", title="T", description="D")
        assert p.solution is None
        p.add_contribution(agent_id="agent-a", domain_id="C1", content="partial result")
        assert p.solution is not None
        assert p.solution.is_complete

    def test_contribution_fields_are_stored(self):
        p = Problem(id="PR1", title="T", description="D")
        c = p.add_contribution(
            agent_id="physics-agent",
            domain_id="P1",
            content="Navier-Stokes partial result",
            artifact_id="art-xyz",
        )
        assert isinstance(c, DomainContribution)
        assert c.agent_id == "physics-agent"
        assert c.domain_id == "P1"
        assert c.content == "Navier-Stokes partial result"
        assert c.artifact_id == "art-xyz"

    def test_multiple_contributions_accumulate(self):
        p = Problem(id="PR1", title="T", description="D")
        p.add_contribution("agent-1", "C1", "climate data")
        p.add_contribution("agent-2", "E1", "energy model")
        p.add_contribution("agent-3", "M1", "mathematical proof")
        assert len(p.solution.contributions) == 3

    def test_contributions_link_to_problem(self):
        p = Problem(id="PR42", title="T", description="D")
        p.add_contribution("a", "X1", "result")
        assert p.solution.problem_id == "PR42"

    def test_contributions_are_returned(self):
        p = Problem(id="PR1", title="T", description="D")
        c1 = p.add_contribution("a1", "C1", "first")
        c2 = p.add_contribution("a2", "E1", "second")
        assert c1.content == "first"
        assert c2.content == "second"

    def test_no_artifact_id_by_default(self):
        p = Problem(id="PR1", title="T", description="D")
        c = p.add_contribution("a", "X1", "result")
        assert c.artifact_id is None
