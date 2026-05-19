"""mars.providers – abstract interface and LLM provider adapters.

Architecture
============
Every provider inherits from ``LLMProvider`` (base.py).
The OpenAI-compatible base (``_openai_compat.py``) handles message
formatting, tool serialisation and response parsing once; thin subclasses
just supply the ``base_url``, default model, and required headers.

Built-in providers
------------------
  anthropic  – Anthropic Claude via the native Anthropic SDK
  copilot    – GitHub Copilot Chat; requires ``gh auth login``
  ollama     – Local Ollama server (completely free, no API key)
  mock       – In-process stub for tests

Adding a new provider
---------------------
Subclass ``OpenAICompatibleProvider`` (for REST/OpenAI-compatible APIs)
or ``LLMProvider`` (for non-OpenAI APIs) and register it in ``registry.py``.

Registry
--------
``get_provider(name, **kwargs)`` is the main entry point.
``list_providers()`` returns all registered names.
"""

from mars.providers._openai_compat import OpenAICompatibleProvider
from mars.providers.anthropic import AnthropicProvider
from mars.providers.base import LLMProvider, LLMMessage, LLMResponse, ToolSpec
from mars.providers.copilot import CopilotProvider
from mars.providers.mock import MockProvider
from mars.providers.ollama import OllamaProvider
from mars.providers.registry import REGISTRY, get_provider, list_providers

__all__ = [
    # Base
    "LLMProvider",
    "LLMMessage",
    "LLMResponse",
    "ToolSpec",
    # Registry
    "get_provider",
    "list_providers",
    "REGISTRY",
    # Compat base (useful for adding new OpenAI-compatible providers)
    "OpenAICompatibleProvider",
    # Built-in providers
    "AnthropicProvider",
    "CopilotProvider",
    "OllamaProvider",
    "MockProvider",
]
