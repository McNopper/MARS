"""MARS Federation Protocol Implementation.

Implements the proprietary MARS-MARS federation protocol for cross-node communication.
This protocol enables MARS nodes to federate and share agents across network boundaries.

Uses Protocol Buffers for efficient serialization with support for:
- Node handshaking and capability exchange
- Agent lifecycle announcements
- Federated messaging
- Artifact transfer
- Connection health monitoring
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

# Import protocol buffers (will be generated from .proto file)
try:
    from mars.server.federation.proto import federation_pb2
    PROTO_BUFFERS_AVAILABLE = True
except ImportError:
    # Fallback to JSON if Protocol Buffers not available
    PROTO_BUFFERS_AVAILABLE = False
    federation_pb2 = None


class MARSFederationProtocol:
    """
    MARS-MARS Federation Protocol implementation.

    Handles cross-node communication including:
    - Node handshakes and discovery
    - Agent lifecycle synchronization
    - Federated message routing
    - Artifact transfer
    - Connection health monitoring
    """

    PROTOCOL_VERSION = "1.0.0"
    MESSAGE_TYPES = {
        "node_handshake",
        "agent_announcement",
        "federated_message",
        "federated_response",
        "artifact_transfer",
        "keepalive",
        "keepalive_ack",
        "federation_error"
    }

    def __init__(self, node_id: str):
        """
        Initialize federation protocol.

        Args:
            node_id: Local node identifier
        """
        self.node_id = node_id
        self._known_nodes: Dict[str, NodeInfo] = {}
        self._active_connections: Dict[str, Any] = {}
        self._virtual_agents: Dict[str, VirtualAgent] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._sequence_number = 0

    # Message serialization

    def serialize_message(self, message_type: str, data: Dict[str, Any]) -> bytes:
        """
        Serialize federation message to bytes.

        Args:
            message_type: Type of federation message
            data: Message data

        Returns:
            Serialized message as bytes
        """
        if PROTO_BUFFERS_AVAILABLE:
            return self._serialize_protobuf(message_type, data)
        else:
            return self._serialize_json(message_type, data)

    def deserialize_message(self, data: bytes) -> Optional[tuple[str, Dict[str, Any]]]:
        """
        Deserialize federation message from bytes.

        Args:
            data: Raw message bytes

        Returns:
            Tuple of (message_type, message_data) or None if deserialization fails
        """
        if PROTO_BUFFERS_AVAILABLE:
            return self._deserialize_protobuf(data)
        else:
            return self._deserialize_json(data)

    def _serialize_json(self, message_type: str, data: Dict[str, Any]) -> bytes:
        """Serialize message as JSON (fallback)."""
        envelope = {
            "message_type": message_type,
            "message_data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": self.PROTOCOL_VERSION
        }
        return json.dumps(envelope).encode("utf-8")

    def _deserialize_json(self, data: bytes) -> Optional[tuple[str, Dict[str, Any]]]:
        """Deserialize JSON message (fallback)."""
        try:
            envelope = json.loads(data.decode("utf-8"))
            message_type = envelope.get("message_type")
            message_data = envelope.get("message_data", {})
            return (message_type, message_data)
        except Exception:
            return None

    def _serialize_protobuf(self, message_type: str, data: Dict[str, Any]) -> bytes:
        """Serialize message using Protocol Buffers."""
        # This would use the generated federation_pb2 classes
        # For now, use JSON as placeholder
        return self._serialize_json(message_type, data)

    def _deserialize_protobuf(self, data: bytes) -> Optional[tuple[str, Dict[str, Any]]]:
        """Deserialize Protocol Buffers message."""
        # This would use the generated federation_pb2 classes
        # For now, use JSON as placeholder
        return self._deserialize_json(data)

    # Message construction

    def build_node_handshake(
        self,
        agents: List[Dict[str, Any]],
        capabilities: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build node handshake message."""
        return {
            "node_id": self.node_id,
            "version": self.PROTOCOL_VERSION,
            "agents": agents,
            "capabilities": capabilities,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "platform": "MARS",
                "protocol_version": self.PROTOCOL_VERSION
            }
        }

    def build_agent_announcement(
        self,
        agent_id: str,
        event: str,
        agent_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build agent announcement message."""
        return {
            "node_id": self.node_id,
            "agent_id": agent_id,
            "event": event,  # "spawn" or "despawn"
            "agent_info": agent_info,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def build_federated_message(
        self,
        source_agent: str,
        target_agent: str,
        payload: Dict[str, Any],
        message_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build federated message."""
        return {
            "source_agent": source_agent,
            "target_agent": target_agent,
            "payload": json.dumps(payload).encode("utf-8") if PROTO_BUFFERS_AVAILABLE else payload,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "message_id": message_id or str(uuid4()),
            "metadata": {
                "source_node": self.node_id
            }
        }

    def build_federated_response(
        self,
        source_agent: str,
        target_agent: str,
        payload: Dict[str, Any],
        message_id: str,
        in_reply_to: str
    ) -> Dict[str, Any]:
        """Build federated response message."""
        return {
            "source_agent": source_agent,
            "target_agent": target_agent,
            "payload": json.dumps(payload).encode("utf-8") if PROTO_BUFFERS_AVAILABLE else payload,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "message_id": message_id,
            "in_reply_to": in_reply_to,
            "metadata": {
                "source_node": self.node_id
            }
        }

    def build_artifact_transfer(
        self,
        artifact_id: str,
        content: bytes,
        tags: List[str],
        mime_type: str = "application/octet-stream"
    ) -> Dict[str, Any]:
        """Build artifact transfer message."""
        return {
            "artifact_id": artifact_id,
            "source_node": self.node_id,
            "content": content,
            "tags": tags,
            "mime_type": mime_type,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "metadata": {}
        }

    def build_keepalive(self) -> Dict[str, Any]:
        """Build keepalive message."""
        self._sequence_number += 1
        return {
            "node_id": self.node_id,
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "sequence": self._sequence_number
        }

    # Node management

    async def register_remote_node(
        self,
        node_id: str,
        version: str,
        capabilities: List[Dict[str, Any]],
        connection: Any
    ) -> None:
        """Register a remote federated node."""
        self._known_nodes[node_id] = NodeInfo(
            node_id=node_id,
            version=version,
            capabilities=capabilities,
            connection=connection,
            registered_at=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc)
        )

    async def unregister_remote_node(self, node_id: str) -> None:
        """Unregister a remote node."""
        self._known_nodes.pop(node_id, None)
        self._active_connections.pop(node_id, None)

        # Remove virtual agents from this node
        to_remove = [
            agent_id for agent_id, agent in self._virtual_agents.items()
            if agent.node_id == node_id
        ]
        for agent_id in to_remove:
            self._virtual_agents.pop(agent_id)

    def get_known_nodes(self) -> List[str]:
        """Get list of known remote nodes."""
        return list(self._known_nodes.keys())

    def get_node_info(self, node_id: str) -> Optional[NodeInfo]:
        """Get information about a known node."""
        return self._known_nodes.get(node_id)

    # Virtual agent management

    async def create_virtual_agent(
        self,
        agent_id: str,
        node_id: str,
        agent_info: Dict[str, Any]
    ) -> VirtualAgent:
        """Create virtual agent for remote agent."""
        virtual_agent = VirtualAgent(
            agent_id=agent_id,
            node_id=node_id,
            agent_info=agent_info,
            created_at=datetime.now(timezone.utc)
        )
        self._virtual_agents[agent_id] = virtual_agent
        return virtual_agent

    async def remove_virtual_agent(self, agent_id: str) -> None:
        """Remove virtual agent."""
        self._virtual_agents.pop(agent_id, None)

    def get_virtual_agent(self, agent_id: str) -> Optional[VirtualAgent]:
        """Get virtual agent by ID."""
        return self._virtual_agents.get(agent_id)

    def get_virtual_agents_by_node(self, node_id: str) -> List[VirtualAgent]:
        """Get all virtual agents from a specific node."""
        return [
            agent for agent in self._virtual_agents.values()
            if agent.node_id == node_id
        ]

    # Message routing

    async def route_to_remote_node(
        self,
        node_id: str,
        message_type: str,
        message_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Route message to remote node."""
        node_info = self.get_node_info(node_id)
        if not node_info:
            raise ValueError(f"Unknown node: {node_id}")

        # Serialize message
        serialized = self.serialize_message(message_type, message_data)

        # Send through node's connection
        connection = node_info.connection
        if hasattr(connection, 'send'):
            await connection.send(serialized)
        else:
            raise ValueError(f"Node connection does not support sending")

        # For request/response patterns, would wait for response here
        return None

    async def broadcast_to_all_nodes(
        self,
        message_type: str,
        message_data: Dict[str, Any],
        exclude_nodes: Optional[Set[str]] = None
    ) -> None:
        """Broadcast message to all known nodes."""
        exclude_nodes = exclude_nodes or set()

        for node_id in self.get_known_nodes():
            if node_id not in exclude_nodes:
                try:
                    await self.route_to_remote_node(node_id, message_type, message_data)
                except Exception as e:
                    print(f"Failed to send to node {node_id}: {e}")

    # Health monitoring

    async def update_node_last_seen(self, node_id: str) -> None:
        """Update node's last seen timestamp."""
        node_info = self.get_node_info(node_id)
        if node_info:
            node_info.last_seen = datetime.now(timezone.utc)

    async def send_keepalive_to_node(self, node_id: str) -> None:
        """Send keepalive to specific node."""
        keepalive = self.build_keepalive()
        await self.route_to_remote_node(node_id, "keepalive", keepalive)

    async def send_keepalive_to_all_nodes(self) -> None:
        """Send keepalive to all known nodes."""
        for node_id in self.get_known_nodes():
            try:
                await self.send_keepalive_to_node(node_id)
            except Exception as e:
                print(f"Failed to send keepalive to node {node_id}: {e}")

    async def cleanup_stale_nodes(self, timeout_seconds: int = 300) -> List[str]:
        """Remove nodes that haven't been seen recently."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        stale_nodes = []

        for node_id, node_info in list(self._known_nodes.items()):
            if node_info.last_seen < cutoff:
                stale_nodes.append(node_id)
                await self.unregister_remote_node(node_id)

        return stale_nodes


# Helper classes

class NodeInfo:
    """Information about a federated node."""

    def __init__(
        self,
        node_id: str,
        version: str,
        capabilities: List[Dict[str, Any]],
        connection: Any,
        registered_at: datetime,
        last_seen: Optional[datetime] = None
    ):
        self.node_id = node_id
        self.version = version
        self.capabilities = capabilities
        self.connection = connection
        self.registered_at = registered_at
        self.last_seen = last_seen or registered_at


class VirtualAgent:
    """Virtual agent representing a remote agent."""

    def __init__(
        self,
        agent_id: str,
        node_id: str,
        agent_info: Dict[str, Any],
        created_at: datetime
    ):
        self.agent_id = agent_id
        self.node_id = node_id
        self.agent_info = agent_info
        self.created_at = created_at
        self.status = "active"

    def to_dict(self) -> Dict[str, Any]:
        """Convert virtual agent to dictionary."""
        return {
            "agent_id": self.agent_id,
            "node_id": self.node_id,
            "name": self.agent_info.get("name", ""),
            "agent_type": self.agent_info.get("agent_type", "unknown"),
            "status": self.status,
            "virtual": True,
            "created_at": self.created_at.isoformat()
        }
