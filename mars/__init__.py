"""MARS – Multi-Agent Runtime System."""

__version__ = "0.1.0"

from mars.client.cli.main import main
from mars.client.providers._openai_compat import OpenAICompatibleProvider
from mars.client.providers.anthropic import AnthropicProvider
from mars.client.providers.base import LLMProvider, LLMMessage, LLMResponse, ToolSpec
from mars.client.providers.copilot import CopilotProvider
from mars.client.providers.mock import MockProvider
from mars.client.providers.ollama import OllamaProvider
from mars.client.providers.registry import REGISTRY, get_provider, list_providers
from mars.storage.artifacts.artifact import Artifact
from mars.storage.artifacts.store import ArtifactStore
from mars.storage.scopes.scope import DomainContribution, Problem, Scope, Solution
from mars.storage.scopes.store import ScopeStore

__all__ = [
    "Artifact",
    "ArtifactStore",
    "main",
    "OpenAICompatibleProvider",
    "AnthropicProvider",
    "LLMProvider",
    "LLMMessage",
    "LLMResponse",
    "ToolSpec",
    "CopilotProvider",
    "MockProvider",
    "OllamaProvider",
    "REGISTRY",
    "get_provider",
    "list_providers",
    "Scope",
    "Problem",
    "Solution",
    "DomainContribution",
    "ScopeStore",
]
