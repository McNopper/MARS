"""mars.artifacts – inter-agent artifact exchange.

Agents can exchange binary payloads (files, archives, images, …) alongside
natural-language messages.  Workflow:

1. Sender creates an Artifact (from bytes, file path, directory, or dict).
2. Sender stores it via ``await self._artifact_store.put(artifact)``,
   receiving an ``artifact_id``.
3. Sender includes the ``artifact_id`` in ``Message.attachments`` or
   mentions it in the message content.
4. Receiver fetches it: ``artifact = await self._artifact_store.get(artifact_id)``.
5. Receiver processes it (``artifact.text()``, ``artifact.to_path(…)``, …).

LLMAgents get built-in tools (``create_text_artifact``,
``create_zip_artifact``, ``read_artifact``, ``list_artifacts``) that handle
steps 1–3 automatically.

See NOTICE for data-handling responsibilities.
"""

from mars.artifacts.artifact import Artifact
from mars.artifacts.store import ArtifactStore

__all__ = ["Artifact", "ArtifactStore"]
