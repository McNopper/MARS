"""Abstract base types for all MARS LLM provider adapters.

This module is intentionally free of vendor SDK imports so it can always
be imported regardless of which optional packages are installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Tool protocol (structural subtyping – avoids circular import with llm.py)
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolSpec(Protocol):
    """Structural protocol satisfied by mars.runtime.services.llm_wire_agent tool definitions.

    Provider adapters accept any object with these three attributes so
    they stay decoupled from the agent layer.
    """

    name: str
    description: str
    parameters: dict[str, Any]


# ---------------------------------------------------------------------------
# Model catalogue type
# ---------------------------------------------------------------------------


@dataclass
class ModelInfo:
    """Metadata about a single model offered by a provider.

    Attributes
    ----------
    id:
        The model identifier string to use as the ``model`` argument,
        e.g. ``"gpt-4o"`` or ``"meta/llama-3.3-70b-instruct"``.
    name:
        Human-readable display name.
    description:
        Short description of capabilities / best use case.
    context_window:
        Maximum context window in tokens (0 = unknown).
    supports_tools:
        Whether the model supports function / tool calling.
    is_free:
        ``True`` when the model is available at no cost (local, free tier, …).
    pricing_notes:
        Optional pricing hint, e.g. ``"$0.15/M input, $0.60/M output"``.
    """

    id: str
    name: str = ""
    description: str = ""
    context_window: int = 0
    supports_tools: bool = True
    is_free: bool = False
    pricing_notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id


# ---------------------------------------------------------------------------
# Message and response types
# ---------------------------------------------------------------------------


@dataclass
class LLMMessage:
    """A single turn in an LLM conversation.

    ``role`` follows the OpenAI convention (system/user/assistant/tool)
    and is translated by each provider adapter into the vendor-specific
    format.
    """

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    # assistant turns that include tool calls
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # tool result turns
    tool_call_id: str | None = None
    name: str | None = None  # tool name (for tool result turns)


@dataclass
class LLMResponse:
    """Normalised response returned by every provider adapter."""

    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    # Provider-specific raw response (for advanced use)
    raw: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract base class for all MARS LLM provider adapters.

    Subclasses must implement ``complete``.  All message history and tool
    definitions are passed in the MARS-internal format (LLMMessage / ToolSpec)
    and each adapter is responsible for translating them into the vendor API
    format.

    Model selection
    ---------------
    Every provider exposes:

    * ``model`` property – get or set the active model identifier.
    * ``KNOWN_MODELS`` class attribute – curated ``{id: ModelInfo}`` dict
      with metadata for models known at release time.
    * ``list_models()`` – async method that returns a live list of
      ``ModelInfo`` objects; falls back to ``KNOWN_MODELS`` when the
      provider does not support a model-listing endpoint.

    Example::

        provider = get_provider("groq")
        models = await provider.list_models()
        provider.model = "gemma2-9b-it"

    Lazy imports
    ------------
    Vendor SDK imports must be deferred to method bodies or ``__init__``
    (guarded by try/except ImportError) so the package can be imported
    without every optional dependency installed.
    """

    #: Human-readable provider name (used in registry and log messages).
    provider_name: str = "unknown"

    #: Whether this provider supports tool / function calling.
    supports_tools: bool = True

    #: Curated model catalogue.  Subclasses populate this at class level.
    KNOWN_MODELS: dict[str, ModelInfo] = {}

    # Subclasses store the active model in self._model.
    _model: str = ""

    # ------------------------------------------------------------------
    # Model selection API
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        """Currently active model identifier."""
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        """Switch to a different model at runtime."""
        self._model = value

    async def list_models(self) -> list[ModelInfo]:
        """Return available models for this provider.

        The default implementation returns the curated ``KNOWN_MODELS``
        catalogue as a list.  Override for providers that expose a live
        model-listing endpoint (see ``OpenAICompatibleProvider``).
        """
        return list(self.KNOWN_MODELS.values())

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion.

        Parameters
        ----------
        messages:
            Full conversation history in MARS format.
        tools:
            Optional list of tools the model may call.  Pass ``None`` or
            omit when tool calling is not needed.
        **kwargs:
            Extra provider-specific parameters (temperature, max_tokens, …).
        """

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider={self.provider_name!r}, model={self._model!r})"
        )
