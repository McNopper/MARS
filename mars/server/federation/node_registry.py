"""Federation Node Registry - Distributed node management for MARS federation.

Manages the registry of federated MARS nodes including their capabilities,
connections, health status, and virtual agent mappings.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from enum import Enum


class NodeStatus(Enum):
    """Federation node connection status"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNHEALTHY = "unhealthy"
    CONNECTING = "connecting"


@dataclass
class FederatedNode:
    """Information about a federated MARS node"""
    node_id: str
    endpoint: str  # Connection endpoint (host:port)
    version: str
    capabilities: List[Dict[str, Any]] = field(default_factory=list)
    status: NodeStatus = NodeStatus.CONNECTING
    connection: Optional[Any] = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_health_check: Optional[datetime] = None
    health_score: float = 1.0  # 0.0 to 1.0
    virtual_agents: Set[str] = field(default_factory=set)  # Virtual agent IDs
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary representation"""
        return {
            "node_id": self.node_id,
            "endpoint": self.endpoint,
            "version": self.version,
            "status": self.status.value,
            "capabilities": self.capabilities,
            "registered_at": self.registered_at.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "health_score": self.health_score,
            "virtual_agent_count": len(self.virtual_agents),
            "metadata": self.metadata
        }


class NodeRegistry:
    """
    Registry for federated MARS nodes.

    Provides:
    - Node registration and discovery
    - Health monitoring and scoring
    - Virtual agent tracking
    - Connection lifecycle management
    - Stale node cleanup
    """

    def __init__(self, local_node_id: str):
        self.local_node_id = local_node_id
        self._nodes: Dict[str, FederatedNode] = {}
        self._lock = asyncio.Lock()
        self._health_check_interval = 60  # seconds
        self._stale_timeout = 300  # seconds (5 minutes)
        self._unhealthy_threshold = 0.5  # health score threshold

    # Node registration

    async def register_node(
        self,
        node_id: str,
        endpoint: str,
        version: str,
        capabilities: List[Dict[str, Any]],
        connection: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> FederatedNode:
        """
        Register a federated node.

        Args:
            node_id: Node identifier
            endpoint: Connection endpoint (host:port)
            version: Node version
            capabilities: List of node capabilities
            connection: Connection object
            metadata: Optional metadata

        Returns:
            Registered FederatedNode
        """
        async with self._lock:
            # If node already exists, update it
            if node_id in self._nodes:
                node = self._nodes[node_id]
                node.endpoint = endpoint
                node.version = version
                node.capabilities = capabilities
                node.connection = connection
                node.status = NodeStatus.CONNECTED
                node.last_seen = datetime.now(timezone.utc)
                node.health_score = 1.0
                if metadata:
                    node.metadata.update(metadata)
                return node

            # Create new node entry
            node = FederatedNode(
                node_id=node_id,
                endpoint=endpoint,
                version=version,
                capabilities=capabilities,
                status=NodeStatus.CONNECTED,
                connection=connection,
                registered_at=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                metadata=metadata or {}
            )

            self._nodes[node_id] = node
            return node

    async def unregister_node(self, node_id: str) -> Optional[FederatedNode]:
        """
        Unregister a federated node.

        Args:
            node_id: Node identifier

        Returns:
            Removed FederatedNode or None if not found
        """
        async with self._lock:
            return self._nodes.pop(node_id, None)

    async def get_node(self, node_id: str) -> Optional[FederatedNode]:
        """
        Get node by ID.

        Args:
            node_id: Node identifier

        Returns:
            FederatedNode or None if not found
        """
        return self._nodes.get(node_id)

    async def list_nodes(
        self,
        status_filter: Optional[NodeStatus] = None,
        min_health_score: Optional[float] = None
    ) -> List[FederatedNode]:
        """
        List federated nodes with optional filtering.

        Args:
            status_filter: Filter by node status
            min_health_score: Filter by minimum health score

        Returns:
            List of FederatedNode matching filters
        """
        nodes = list(self._nodes.values())

        if status_filter:
            nodes = [n for n in nodes if n.status == status_filter]

        if min_health_score is not None:
            nodes = [n for n in nodes if n.health_score >= min_health_score]

        return nodes

    async def get_active_nodes(self) -> List[FederatedNode]:
        """Get all connected and healthy nodes."""
        return await self.list_nodes(
            status_filter=NodeStatus.CONNECTED,
            min_health_score=self._unhealthy_threshold
        )

    # Health monitoring

    async def update_node_health(
        self,
        node_id: str,
        health_score: float,
        status_override: Optional[NodeStatus] = None
    ) -> None:
        """
        Update node health information.

        Args:
            node_id: Node identifier
            health_score: Health score (0.0 to 1.0)
            status_override: Optional status override
        """
        async with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return

            node.health_score = health_score
            node.last_health_check = datetime.now(timezone.utc)

            if status_override:
                node.status = status_override
            else:
                # Auto-determine status based on health score
                if health_score < self._unhealthy_threshold:
                    node.status = NodeStatus.UNHEALTHY
                elif node.status == NodeStatus.CONNECTING:
                    node.status = NodeStatus.CONNECTED

    async def update_last_seen(self, node_id: str) -> None:
        """
        Update node's last seen timestamp.

        Args:
            node_id: Node identifier
        """
        async with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.last_seen = datetime.now(timezone.utc)

    async def mark_node_unhealthy(self, node_id: str) -> None:
        """Mark node as unhealthy."""
        await self.update_node_health(node_id, 0.0, NodeStatus.UNHEALTHY)

    async def mark_node_disconnected(self, node_id: str) -> None:
        """Mark node as disconnected."""
        async with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.status = NodeStatus.DISCONNECTED

    # Virtual agent tracking

    async def add_virtual_agent(self, node_id: str, agent_id: str) -> bool:
        """
        Add virtual agent to node.

        Args:
            node_id: Node identifier
            agent_id: Virtual agent identifier

        Returns:
            True if agent was added, False if node not found
        """
        async with self._lock:
            node = self._nodes.get(node_id)
            if node:
                node.virtual_agents.add(agent_id)
                return True
            return False

    async def remove_virtual_agent(self, node_id: str, agent_id: str) -> bool:
        """
        Remove virtual agent from node.

        Args:
            node_id: Node identifier
            agent_id: Virtual agent identifier

        Returns:
            True if agent was removed, False if not found
        """
        async with self._lock:
            node = self._nodes.get(node_id)
            if node and agent_id in node.virtual_agents:
                node.virtual_agents.remove(agent_id)
                return True
            return False

    async def get_virtual_agents(self, node_id: str) -> Set[str]:
        """
        Get virtual agents for a node.

        Args:
            node_id: Node identifier

        Returns:
            Set of virtual agent IDs
        """
        node = await self.get_node(node_id)
        return node.virtual_agents if node else set()

    # Cleanup and maintenance

    async def cleanup_stale_nodes(self, timeout_seconds: Optional[int] = None) -> List[str]:
        """
        Remove nodes that haven't been seen recently.

        Args:
            timeout_seconds: Timeout in seconds (uses default if not provided)

        Returns:
            List of node IDs that were removed
        """
        timeout = timeout_seconds or self._stale_timeout
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)
        stale_nodes = []

        async with self._lock:
            for node_id, node in list(self._nodes.items()):
                if node.last_seen < cutoff:
                    stale_nodes.append(node_id)
                    # Close connection if possible
                    if hasattr(node.connection, 'close'):
                        try:
                            await node.connection.close()
                        except Exception:
                            pass

                    del self._nodes[node_id]

        return stale_nodes

    async def get_node_count(self) -> int:
        """Get total number of registered nodes."""
        return len(self._nodes)

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry statistics
        """
        nodes = list(self._nodes.values())

        total_nodes = len(nodes)
        connected_nodes = len([n for n in nodes if n.status == NodeStatus.CONNECTED])
        unhealthy_nodes = len([n for n in nodes if n.status == NodeStatus.UNHEALTHY])
        disconnected_nodes = len([n for n in nodes if n.status == NodeStatus.DISCONNECTED])

        total_virtual_agents = sum(len(n.virtual_agents) for n in nodes)

        avg_health_score = 0.0
        if nodes:
            avg_health_score = sum(n.health_score for n in nodes) / len(nodes)

        return {
            "total_nodes": total_nodes,
            "connected_nodes": connected_nodes,
            "unhealthy_nodes": unhealthy_nodes,
            "disconnected_nodes": disconnected_nodes,
            "total_virtual_agents": total_virtual_agents,
            "average_health_score": avg_health_score,
            "local_node_id": self.local_node_id
        }

    # Node discovery

    async def find_nodes_by_capability(self, capability_name: str) -> List[FederatedNode]:
        """
        Find nodes that have a specific capability.

        Args:
            capability_name: Capability to search for

        Returns:
            List of nodes with the capability
        """
        matching_nodes = []

        for node in await self.get_active_nodes():
            for cap in node.capabilities:
                if cap.get("name") == capability_name or capability_name.lower() in cap.get("description", "").lower():
                    matching_nodes.append(node)
                    break

        return matching_nodes

    async def export_registry_json(self) -> Dict[str, Any]:
        """
        Export registry state as JSON.

        Returns:
            Dictionary containing registry state
        """
        nodes_data = {}
        for node_id, node in self._nodes.items():
            nodes_data[node_id] = node.to_dict()

        return {
            "local_node_id": self.local_node_id,
            "nodes": nodes_data,
            "statistics": await self.get_statistics(),
            "exported_at": datetime.now(timezone.utc).isoformat()
        }

    async def import_registry_json(self, registry_json: Dict[str, Any]) -> int:
        """
        Import registry state from JSON.

        Args:
            registry_json: Dictionary containing registry state

        Returns:
            Number of nodes imported
        """
        imported = 0
        nodes_data = registry_json.get("nodes", {})

        for node_id, node_data in nodes_data.items():
            try:
                # Import node (without connection for remote import)
                node = FederatedNode(
                    node_id=node_id,
                    endpoint=node_data.get("endpoint", ""),
                    version=node_data.get("version", "unknown"),
                    capabilities=node_data.get("capabilities", []),
                    status=NodeStatus.DISCONNECTED,  # Import as disconnected
                    connection=None,  # No connection on import
                    registered_at=datetime.fromisoformat(node_data.get("registered_at", datetime.now(timezone.utc).isoformat())),
                    last_seen=datetime.fromisoformat(node_data.get("last_seen", datetime.now(timezone.utc).isoformat())),
                    metadata=node_data.get("metadata", {})
                )

                self._nodes[node_id] = node
                imported += 1

            except Exception as e:
                print(f"Error importing node {node_id}: {e}")
                continue

        return imported
