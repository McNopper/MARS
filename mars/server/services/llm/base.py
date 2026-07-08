"""Abstract base types for all MARS LLM provider adapters.

This module is intentionally free of vendor SDK imports so it can always
be imported regardless of which optional packages are installed.
"""

from __future__ import annotations

import os
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from mars.server.services.base import Service, ServiceCapability


def env_int(name: str, default: int) -> int:
    """Read a non-negative int from the environment, falling back to *default*.

    Shared by the provider adapters so env-tunable knobs (retry counts, context
    size, …) resolve identically everywhere.
    """
    try:
        v = int(os.environ.get(name, "").strip())
        return v if v >= 0 else default
    except (ValueError, AttributeError):
        return default

# ---------------------------------------------------------------------------
# Tool protocol (structural subtyping – avoids circular import with llm.py)
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolSpec(Protocol):
    """Structural protocol satisfied by mars.server.services.llm_wire_agent tool definitions.

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
    # Extended/interleaved thinking emitted by the assistant on this turn.
    # Must be replayed verbatim (with its signature) on tool-use turns so
    # providers like Anthropic can validate the reasoning chain across rounds.
    thinking: str | None = None
    thinking_signature: str | None = None


@dataclass
class LLMResponse:
    """Normalised response returned by every provider adapter."""

    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    # Extended/interleaved thinking returned with this response, and its
    # provider signature (Anthropic).  Carried back onto the next assistant
    # LLMMessage so thinking survives across tool-call rounds.
    thinking: str | None = None
    thinking_signature: str | None = None
    # Provider-specific raw response (for advanced use)
    raw: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(Service):
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

        provider = get_service("groq")
        models = await provider.list_models()
        provider.model = "gemma2-9b-it"

    Lazy imports
    ------------
    Vendor SDK imports must be deferred to method bodies or ``__init__``
    (guarded by try/except ImportError) so the package can be imported
    without every optional dependency installed.
    """

    service_type: str = "llm"

    #: Human-readable provider name (used in registry and log messages).
    provider_name: str = "unknown"

    #: Whether this provider supports tool / function calling.
    supports_tools: bool = True

    #: Curated model catalogue.  Subclasses populate this at class level.
    KNOWN_MODELS: dict[str, ModelInfo] = {}

    # Subclasses store the active model in self._model.
    _model: str = ""
    _running: bool = False

    # ------------------------------------------------------------------
    # Service interface
    # ------------------------------------------------------------------

    @property
    def service_id(self) -> str:
        """Service identifier is the provider name."""
        return self.provider_name

    @property
    def display_name(self) -> str:
        """Human-readable display name."""
        return self.provider_name

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """LLM services expose their models as capabilities."""
        caps = []
        for model_id, model_info in self.KNOWN_MODELS.items():
            caps.append(ServiceCapability(
                name=model_id,
                description=model_info.description or f"Model: {model_info.name}",
                input_schema=None,
            ))
        return caps

    async def initialize(self) -> None:
        """Start the LLM provider service."""
        self._running = True

    async def shutdown(self) -> None:
        """Stop the LLM provider service."""
        self._running = False

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a tool - for LLMs, this means running a completion."""
        # For LLM services, "calling a tool" means generating text
        # This is used by agents that need to invoke the LLM
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools")
        response = await self.complete(messages, tools)
        return response

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

    @property
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._running

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider={self.provider_name!r}, model={self._model!r})"
        )
