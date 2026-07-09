"""
A2A Agent Card Manager

Generates and manages A2A Agent Cards for agent discovery and interoperability.
Agent Cards provide JSON metadata describing agent identity, capabilities, and endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class AgentType(Enum):
    """Standard agent types for Agent Cards"""
    LLM = "llm"
    SERVICE = "service"
    HUMAN = "human"
    BRIDGE = "bridge"
    TOOL = "tool"


@dataclass
class AgentCapability:
    """Agent capability description"""
    name: str
    description: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None


@dataclass
class AgentEndpoint:
    """Agent endpoint information"""
    protocol: str  # e.g., "a2a", "mcp", "http"
    url: str
    authentication: Optional[str] = None  # e.g., "bearer", "mtls", "none"


@dataclass
class AgentAuthentication:
    """Agent authentication requirements"""
    type: str  # e.g., "none", "bearer_token", "mtls", "api_key"
    description: Optional[str] = None
    requirements: Optional[Dict[str, Any]] = None


@dataclass
class AgentCard:
    """A2A Agent Card representation"""
    agent_id: str
    name: str
    version: str
    description: str
    agent_type: AgentType
    capabilities: List[AgentCapability] = field(default_factory=list)
    endpoints: Dict[str, AgentEndpoint] = field(default_factory=dict)
    authentication: AgentAuthentication = field(default_factory=lambda: AgentAuthentication(type="none"))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert Agent Card to dictionary representation"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "agent_type": self.agent_type.value,
            "capabilities": [
                {
                    "name": cap.name,
                    "description": cap.description,
                    "input_schema": cap.input_schema,
                    "output_schema": cap.output_schema
                }
                for cap in self.capabilities
            ],
            "endpoints": {
                name: {
                    "protocol": ep.protocol,
                    "url": ep.url,
                    "authentication": ep.authentication
                }
                for name, ep in self.endpoints.items()
            },
            "authentication": {
                "type": self.authentication.type,
                "description": self.authentication.description,
                "requirements": self.authentication.requirements
            },
            "metadata": self.metadata
        }


class AgentCardManager:
    """
    Manages A2A Agent Cards for agent discovery.

    Provides:
    - Agent Card generation from MARS agents
    - Agent Card caching and lookup
    - Capability extraction
    - Endpoint configuration
    """

    def __init__(self):
        self._cards: Dict[str, AgentCard] = {}
        self._capabilities_cache: Dict[str, List[AgentCapability]] = {}

    async def generate_agent_card(
        self,
        agent_id: str,
        agent_name: str,
        agent_type: str,
        capabilities: Optional[List[Dict[str, Any]]] = None,
        base_url: str = "a2a://mars.local"
    ) -> AgentCard:
        """
        Generate Agent Card from MARS agent information.

        Args:
            agent_id: Agent identifier
            agent_name: Agent display name
            agent_type: Agent type (llm, service, human, bridge)
            capabilities: List of agent capabilities/tools
            base_url: Base URL for agent endpoints

        Returns:
            Generated AgentCard
        """
        # Map agent type
        agent_type_enum = self._map_agent_type(agent_type)

        # Build capabilities
        agent_capabilities = []
        if capabilities:
            for cap in capabilities:
                agent_capabilities.append(
                    AgentCapability(
                        name=cap.get("name", ""),
                        description=cap.get("description", ""),
                        input_schema=cap.get("input_schema"),
                        output_schema=cap.get("output_schema")
                    )
                )

        # Build endpoints
        endpoints = {
            "a2a": AgentEndpoint(
                protocol="a2a",
                url=f"{base_url}/agents/{agent_id}",
                authentication="none"
            )
        }

        # Create authentication info
        authentication = AgentAuthentication(type="none")

        # Create agent card
        card = AgentCard(
            agent_id=agent_id,
            name=agent_name,
            version="1.0.0",
            description=f"{agent_type} agent: {agent_name}",
            agent_type=agent_type_enum,
            capabilities=agent_capabilities,
            endpoints=endpoints,
            authentication=authentication,
            metadata={
                "platform": "MARS",
                "mars_version": "1.0.0"
            }
        )

        # Cache the card
        self._cards[agent_id] = card
        self._capabilities_cache[agent_id] = agent_capabilities

        return card

    async def get_agent_card(self, agent_id: str) -> Optional[AgentCard]:
        """
        Get cached Agent Card.

        Args:
            agent_id: Agent identifier

        Returns:
            AgentCard or None if not found
        """
        return self._cards.get(agent_id)

    async def update_agent_card(
        self,
        agent_id: str,
        capabilities: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[AgentCard]:
        """
        Update existing Agent Card.

        Args:
            agent_id: Agent identifier
            capabilities: Updated capabilities list

        Returns:
            Updated AgentCard or None if not found
        """
        card = self._cards.get(agent_id)
        if not card:
            return None

        # Update capabilities
        if capabilities:
            new_capabilities = []
            for cap in capabilities:
                new_capabilities.append(
                    AgentCapability(
                        name=cap.get("name", ""),
                        description=cap.get("description", ""),
                        input_schema=cap.get("input_schema"),
                        output_schema=cap.get("output_schema")
                    )
                )
            card.capabilities = new_capabilities
            self._capabilities_cache[agent_id] = new_capabilities

        return card

    async def remove_agent_card(self, agent_id: str) -> bool:
        """
        Remove Agent Card from cache.

        Args:
            agent_id: Agent identifier

        Returns:
            True if card was removed, False if not found
        """
        if agent_id in self._cards:
            del self._cards[agent_id]
            self._capabilities_cache.pop(agent_id, None)
            return True
        return False

    async def list_agent_cards(self) -> List[AgentCard]:
        """
        List all cached Agent Cards.

        Returns:
            List of all AgentCards
        """
        return list(self._cards.values())

    async def find_agents_by_capability(self, capability_name: str) -> List[str]:
        """
        Find agents that have a specific capability.

        Args:
            capability_name: Name of capability to search for

        Returns:
            List of agent IDs with the capability
        """
        matching_agents = []

        for agent_id, capabilities in self._capabilities_cache.items():
            for cap in capabilities:
                if cap.name == capability_name:
                    matching_agents.append(agent_id)
                    break

        return matching_agents

    async def get_agent_capabilities(self, agent_id: str) -> List[AgentCapability]:
        """
        Get agent capabilities from cache.

        Args:
            agent_id: Agent identifier

        Returns:
            List of AgentCapability or empty list if not found
        """
        return self._capabilities_cache.get(agent_id, [])

    def _map_agent_type(self, agent_type: str) -> AgentType:
        """Map MARS agent type to A2A AgentType"""
        type_mapping = {
            "llm": AgentType.LLM,
            "service": AgentType.SERVICE,
            "human": AgentType.HUMAN,
            "bridge": AgentType.BRIDGE,
            "tool": AgentType.TOOL
        }
        return type_mapping.get(agent_type.lower(), AgentType.SERVICE)

    async def export_agent_cards_json(self) -> Dict[str, Dict[str, Any]]:
        """
        Export all Agent Cards as JSON.

        Returns:
            Dictionary mapping agent_id to Agent Card JSON
        """
        return {
            agent_id: card.to_dict()
            for agent_id, card in self._cards.items()
        }

    async def import_agent_cards_json(self, cards_json: Dict[str, Dict[str, Any]]) -> int:
        """
        Import Agent Cards from JSON.

        Args:
            cards_json: Dictionary mapping agent_id to Agent Card JSON

        Returns:
            Number of cards imported
        """
        imported = 0

        for agent_id, card_json in cards_json.items():
            try:
                capabilities = [
                    AgentCapability(
                        name=cap.get("name", ""),
                        description=cap.get("description", ""),
                        input_schema=cap.get("input_schema"),
                        output_schema=cap.get("output_schema")
                    )
                    for cap in card_json.get("capabilities", [])
                ]

                endpoints = {}
                for name, ep_data in card_json.get("endpoints", {}).items():
                    endpoints[name] = AgentEndpoint(
                        protocol=ep_data.get("protocol", ""),
                        url=ep_data.get("url", ""),
                        authentication=ep_data.get("authentication")
                    )

                auth_data = card_json.get("authentication", {})
                authentication = AgentAuthentication(
                    type=auth_data.get("type", "none"),
                    description=auth_data.get("description"),
                    requirements=auth_data.get("requirements")
                )

                card = AgentCard(
                    agent_id=card_json.get("agent_id", agent_id),
                    name=card_json.get("name", ""),
                    version=card_json.get("version", "1.0.0"),
                    description=card_json.get("description", ""),
                    agent_type=AgentType(card_json.get("agent_type", "service")),
                    capabilities=capabilities,
                    endpoints=endpoints,
                    authentication=authentication,
                    metadata=card_json.get("metadata", {})
                )

                self._cards[agent_id] = card
                self._capabilities_cache[agent_id] = capabilities
                imported += 1

            except Exception as e:
                print(f"Error importing Agent Card for {agent_id}: {e}")
                continue

        return imported
