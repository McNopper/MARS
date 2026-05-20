"""Artifact data model for MARS inter-agent file exchange.

Agents can exchange binary artifacts (files, archives, images, …) alongside
natural-language messages. An Artifact is identified by a UUID; messages
carry artifact IDs in their ``attachments`` list. The receiving agent fetches
the artifact from the platform's shared ArtifactStore.

Legal note: see NOTICE for data-handling responsibilities when artifact
content is included in LLM prompts sent to external provider APIs.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Artifact:
    """A named, typed binary payload exchanged between MARS agents.

    Parameters
    ----------
    name:
        Human-readable filename, including extension (e.g. ``"report.zip"``).
    data:
        Raw bytes of the artifact payload.
    mime_type:
        IANA media type.  Detected automatically by :meth:`from_path` and
        :meth:`from_directory`.  Defaults to ``"application/octet-stream"``.
    artifact_id:
        Unique identifier (UUIDv4).  Auto-generated if not supplied.
    created_by:
        Agent ID of the creating agent (set by the ArtifactStore).
    scope_id:
        Optional scope ID this artifact satisfies.
    created_at:
        UTC timestamp of creation.
    metadata:
        Arbitrary key-value pairs for application-level annotations.
    """

    name: str
    data: bytes
    mime_type: str = "application/octet-stream"
    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_by: str | None = None
    scope_id: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Size of the artifact payload in bytes."""
        return len(self.data)

    @property
    def size_human(self) -> str:
        """Human-readable size string (e.g. ``"1.2 KB"``)."""
        n = self.size
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
            n /= 1024  # type: ignore[assignment]
        return f"{n:.1f} TB"

    @property
    def checksum(self) -> str:
        """SHA-256 hex digest of the artifact payload."""
        return hashlib.sha256(self.data).hexdigest()

    def is_text(self) -> bool:
        """Return True when the MIME type indicates textual content."""
        return self.mime_type.startswith("text/") or self.mime_type in {
            "application/json",
            "application/xml",
            "application/yaml",
            "application/x-yaml",
            "application/javascript",
            "application/x-sh",
        }

    def text(self, encoding: str = "utf-8") -> str:
        """Decode payload as text.  Raises ``UnicodeDecodeError`` for binary."""
        return self.data.decode(encoding)

    def to_text(self, encoding: str = "utf-8") -> str:
        """Alias for :meth:`text` for naming symmetry with factory helpers."""
        return self.text(encoding=encoding)

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Artifact":
        """Create an artifact from a file on disk.

        The MIME type is detected from the file extension via the standard
        ``mimetypes`` library; unknown extensions fall back to
        ``"application/octet-stream"``.
        """
        p = Path(path)
        data = p.read_bytes()
        mime, _ = mimetypes.guess_type(str(p))
        return cls(
            name=p.name,
            data=data,
            mime_type=mime or "application/octet-stream",
            created_by=created_by,
            metadata=metadata or {},
        )

    @classmethod
    def from_directory(
        cls,
        directory: str | Path,
        archive_name: str | None = None,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Artifact":
        """Zip an entire directory tree and return it as an artifact.

        Parameters
        ----------
        directory:
            Path to the directory to archive.
        archive_name:
            Name of the resulting artifact (default: ``<dirname>.zip``).
        """
        d = Path(directory)
        if not d.is_dir():
            raise ValueError(f"Not a directory: {d}")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(d.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, arcname=file_path.relative_to(d))

        return cls(
            name=archive_name or f"{d.name}.zip",
            data=buf.getvalue(),
            mime_type="application/zip",
            created_by=created_by,
            metadata={"source_directory": str(d), **(metadata or {})},
        )

    @classmethod
    def from_text(
        cls,
        name: str,
        content: str,
        mime_type: str = "text/plain",
        encoding: str = "utf-8",
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Artifact":
        """Create a text artifact from a string."""
        return cls.from_bytes(
            name=name,
            data=content.encode(encoding),
            mime_type=mime_type,
            created_by=created_by,
            metadata=metadata,
        )

    @classmethod
    def from_bytes(
        cls,
        name: str,
        data: bytes,
        mime_type: str = "application/octet-stream",
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Artifact":
        """Create an artifact directly from raw bytes."""
        return cls(
            name=name,
            data=data,
            mime_type=mime_type,
            created_by=created_by,
            metadata=metadata or {},
        )

    @classmethod
    def from_zip_dict(
        cls,
        archive_name: str,
        files: dict[str, str | bytes],
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Artifact":
        """Create a zip artifact from an in-memory dict of filename → content.

        Parameters
        ----------
        archive_name:
            Name of the resulting ``.zip`` artifact.
        files:
            Mapping of relative file path → string or bytes content.
            Example::

                files = {
                    "README.md": "# My project",
                    "src/main.py": "print('hello')",
                }
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for filename, content in files.items():
                data = content.encode() if isinstance(content, str) else content
                zf.writestr(filename, data)
        return cls(
            name=archive_name,
            data=buf.getvalue(),
            mime_type="application/zip",
            created_by=created_by,
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def to_path(self, path: str | Path) -> Path:
        """Write the artifact payload to disk and return the resolved path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.data)
        return p.resolve()

    def list_zip_contents(self) -> list[str] | None:
        """Return the list of files inside a zip artifact, or None if not a zip."""
        if "zip" not in self.mime_type:
            return None
        with zipfile.ZipFile(io.BytesIO(self.data)) as zf:
            return zf.namelist()

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary (no raw bytes)."""
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "size_human": self.size_human,
            "checksum_sha256": self.checksum,
            "created_by": self.created_by,
            "scope_id": self.scope_id,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        return (
            f"Artifact(id={self.artifact_id[:8]!r}, name={self.name!r}, "
            f"type={self.mime_type!r}, size={self.size_human})"
        )
