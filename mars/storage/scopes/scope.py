"""Scope, Problem, Solution, and DomainContribution dataclasses.

Architecture
------------
Scope
    A static domain definition loaded from a .md file (e.g. M1 Mathematics,
    C1 Climate).  Scopes are permanent knowledge arenas — they never carry
    runtime lifecycle state.

Problem
    A specific challenge posed *within* one or more domain Scopes.  Problems
    are the active work units in MARS: agents are assigned to a Problem and
    their goal is to search for sub-solutions that together form a Solution.

    Status lifecycle:  open → assigned → in_progress → solved | closed

Solution
    The composite answer to a Problem.  A Solution is *subdivided* into
    DomainContributions — one per participating domain agent.  The quality of
    the overall Solution emerges from the synthesis of all contributions.

DomainContribution
    A partial sub-solution contributed by one agent from a specific domain
    Scope.  Multiple DomainContributions compose a single Solution.

Mapping to prior work
---------------------
- Contract Net Protocol (Smith 1980): Problem ↔ task announcement,
  DomainContribution ↔ bid/result from a contractor agent.
- EMIKA sub-scope decomposition (Müller et al. 2004): Solution subdivision
  mirrors the sub-scope result aggregation pattern.
- BDI goal model (Rao & Georgeff 1995): Problem ↔ agent goal,
  Solution search ↔ plan execution toward a desire.
- Distributed problem solving: DomainContributions are dispersed partial
  knowledge; the Solution synthesis emerges from agent collaboration without
  a central planner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Scope:
    """Static domain definition — loaded from .md files.

    A Scope is a permanent knowledge arena (e.g. M1 Mathematics, C1 Climate).
    It carries no runtime lifecycle; Problems are posed *within* Scopes.
    Sub-scopes live in subdirectories: scopes/M1/M1.1.md
    """

    id: str
    title: str
    document: str
    path: str
    parent_id: str | None = None
    #: Skills parsed from the ``## Agent Skills Needed`` section.
    required_skills: list[str] = field(default_factory=list)

    @property
    def children(self) -> list[str]:
        """Child scope IDs are inferred by the ScopeStore, not stored here."""
        return []


@dataclass
class DomainContribution:
    """A sub-solution contributed by one agent from a specific domain Scope.

    A Solution is subdivided into DomainContributions — each specialist agent
    contributes partial knowledge from its domain.  Contributions are later
    synthesised into the composite Solution.
    """

    agent_id: str
    domain_id: str          # which Scope domain this addresses, e.g. "C1", "M1"
    content: str
    artifact_id: str | None = None
    ts: datetime = field(default_factory=datetime.now)


@dataclass
class Solution:
    """Composite solution to a Problem.

    Built from DomainContributions — one per participating domain agent.
    The Solution is subdivided; its completeness grows as more agents
    contribute from their respective domains.
    """

    problem_id: str
    contributions: list[DomainContribution] = field(default_factory=list)
    summary: str = ""
    ts: datetime = field(default_factory=datetime.now)

    def add(self, contribution: DomainContribution) -> None:
        """Append a domain contribution."""
        self.contributions.append(contribution)

    @property
    def is_complete(self) -> bool:
        """True when at least one contribution exists."""
        return len(self.contributions) > 0


@dataclass
class Problem:
    """A challenge posed within one or more domain Scopes.

    Problems are the active work items of MARS.  An agent's goal is to search
    for a sub-solution (DomainContribution) that, together with contributions
    from other domain agents, forms a complete composite Solution.

    Status lifecycle:  open → assigned → in_progress → solved | closed
    """

    id: str
    title: str
    description: str
    scope_ids: list[str] = field(default_factory=list)   # domain Scope IDs spanned
    status: str = "open"
    #: Skills required across all contributing domains.
    required_skills: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    solution: Solution | None = None
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 0            # 0 = normal, 1 = high, 2 = urgent
    deadline: str | None = None  # ISO datetime string

    VALID_STATUSES = frozenset({"open", "assigned", "in_progress", "solved", "closed"})

    def add_contribution(
        self,
        agent_id: str,
        domain_id: str,
        content: str,
        artifact_id: str | None = None,
    ) -> DomainContribution:
        """Record a domain agent's sub-solution and attach it to this problem's Solution."""
        if self.solution is None:
            self.solution = Solution(problem_id=self.id)
        contrib = DomainContribution(
            agent_id=agent_id,
            domain_id=domain_id,
            content=content,
            artifact_id=artifact_id,
        )
        self.solution.add(contrib)
        return contrib
