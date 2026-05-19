"""ScopeStore — loads Scope documents from the scopes/ filesystem tree."""
from __future__ import annotations

import re
from pathlib import Path

from mars.scopes.scope import Scope


class ScopeStore:
    """Scans a directory tree of .md files and assembles a Scope list.

    Directory structure encodes hierarchy:
        scopes/S1.md              → Scope(id="S1", parent_id=None)
        scopes/S1/S1.1.md         → Scope(id="S1.1", parent_id="S1")
        scopes/S1/S1.1/S1.1.1.md  → Scope(id="S1.1.1", parent_id="S1.1")
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def load_all(self) -> list[Scope]:
        """Return all Scopes found in root, sorted by ID."""
        if not self.root.exists():
            return []
        scopes: list[Scope] = []
        for md_path in sorted(self.root.rglob("*.md")):
            rel = md_path.relative_to(self.root)
            scope_id = md_path.stem
            parts = rel.parts
            parent_id = parts[-2] if len(parts) > 1 else None
            document = md_path.read_text(encoding="utf-8")
            title = self._extract_title(document, scope_id)
            required_skills = self._extract_required_skills(document)
            scopes.append(
                Scope(
                    id=scope_id,
                    title=title,
                    document=document,
                    path=str(rel).replace("\\", "/"),
                    parent_id=parent_id,
                    required_skills=required_skills,
                )
            )
        return scopes

    def write(self, scope_id: str, document: str, parent_id: str | None = None) -> Path:
        """Write a scope document to disk and return its path."""
        folder = self.root / parent_id if parent_id else self.root
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{scope_id}.md"
        path.write_text(document, encoding="utf-8")
        return path

    def next_id(self, parent_id: str | None = None) -> str:
        """Return the next available scope ID under parent_id."""
        existing = self.load_all()
        if parent_id is None:
            siblings = [s for s in existing if s.parent_id is None]
            nums: list[int] = []
            for scope in siblings:
                match = re.match(r"^S(\d+)$", scope.id)
                if match:
                    nums.append(int(match.group(1)))
            return f"S{max(nums, default=0) + 1}"

        siblings = [s for s in existing if s.parent_id == parent_id]
        nums = []
        prefix = f"{parent_id}."
        for scope in siblings:
            if scope.id.startswith(prefix):
                tail = scope.id[len(prefix):]
                match = re.match(r"^(\d+)$", tail)
                if match:
                    nums.append(int(match.group(1)))
        return f"{parent_id}.{max(nums, default=0) + 1}"

    @staticmethod
    def _extract_title(document: str, fallback: str) -> str:
        for line in document.splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip()
        for line in document.splitlines():
            line = line.strip()
            if line:
                return line[:60]
        return fallback

    @staticmethod
    def _extract_required_skills(document: str) -> list[str]:
        """Parse skills listed under '## Agent Skills Needed' section.

        Accepts comma-separated backtick-quoted tokens, e.g.:
            `physics`, `symbolic-math`, `numerics`
        """
        in_section = False
        skills: list[str] = []
        for line in document.splitlines():
            stripped = line.strip()
            if re.match(r"^#{1,3}\s+Agent Skills Needed", stripped, re.IGNORECASE):
                in_section = True
                continue
            if in_section:
                if stripped.startswith("#"):
                    break  # next section starts
                found = re.findall(r"`([^`]+)`", stripped)
                skills.extend(s.strip().lower() for s in found if s.strip())
        return skills
