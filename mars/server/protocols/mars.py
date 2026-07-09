"""
MARS Federation Protocol Adapter

Implements the proprietary MARS-MARS federation protocol for cross-node communication.
This protocol enables MARS nodes to federate and share agents across network boundaries.
"""

import json
from typing import Any, Dict, Optional, List

from .base import (
    ProtocolAdapter,
    ProtocolInfo,
    ProtocolType,
    MessageHandlerError,
    ProtocolAdapterError
)


class MARSProtocolAdapter(ProtocolAdapter):
    """
    MARS Federation Protocol Adapter

    Implements MARS-MARS protocol for node federation:
    - node_handshake - Node identity and capability exchange
    - agent_announcement - Remote agent lifecycle events
    - federated_message - Message to remote agent
    - federated_response - Response from remote agent
    - artifact_transfer - Cross-node artifact sharing
    - keepalive - Connection health monitoring

    Protocol Features:
    - TCP with custom binary framing
    - Protocol Buffers for efficiency (future enhancement)
    - TLS with mutual authentication (future enhancement)
    - Distributed agent registry
    """

    # MARS protocol identifiers
    MARS_PROTOCOL_VERSION = "1.0.0"
    MARS_MAGIC_HEADER = b"MARS-FED/"

    # Protocol message types
    MSG_NODE_HANDSHAKE = "node_handshake"
    MSG_AGENT_ANNOUNCEMENT = "agent_announcement"
    MSG_FEDERATED_MESSAGE = "federated_message"
    MSG_FEDERATED_RESPONSE = "federated_response"
    MSG_ARTIFACT_TRANSFER = "artifact_transfer"
    MSG_KEEPALIVE = "keepalive"

    def __init__(self, server: Any):
        super().__init__(server)
        # Initialize managers from server if available
        self._node_registry = getattr(server, '_node_registry', None)
        self._security_manager = getattr(server, '_security_manager', None)
        self._protocol_info = ProtocolInfo(
            name="MARS",
            version=self.MARS_PROTOCOL_VERSION,
            protocol_type=ProtocolType.MARS,
            capabilities=[
                "node_handshake",
                "agent_announcement",
                "federated_message",
                "federated_response",
                "artifact_transfer",
                "keepalive"
            ],
            description="MARS-MARS federation protocol"
        )

    def get_protocol_info(self) -> ProtocolInfo:
        """Return MARS protocol metadata"""
        return self._protocol_info

    def supports_protocol(self, protocol_identifier: Any) -> bool:
        """
        Check if data is MARS federation message.

        Args:
            protocol_identifier: Raw bytes or message dict to check

        Returns:
            True if data is MARS federation format
        """
        if isinstance(protocol_identifier, bytes):
            return protocol_identifier.startswith(self.MARS_MAGIC_HEADER)
        elif isinstance(protocol_identifier, dict):
            return "msg_type" in protocol_identifier
        return False

    async def serialize_message(self, message: Dict[str, Any]) -> bytes:
        """
        Serialize message to MARS federation format.

        Currently uses JSON with magic header. Will migrate to Protocol Buffers.

        Args:
            message: Message dictionary to serialize

        Returns:
            Serialized message as bytes
        """
        # MARS format: "MARS-FED/<version>\nJSON\n" (JSON on separate line)
        json_str = json.dumps(message)
        return f"{self.MARS_MAGIC_HEADER.decode()}{self.MARS_PROTOCOL_VERSION}\n{json_str}\n".encode()

    async def deserialize_message(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize MARS federation message.

        Args:
            data: Raw message bytes

        Returns:
            Deserialized message dictionary

        Raises:
            ProtocolAdapterError: If deserialization fails
        """
        try:
            # Parse MARS format: "MARS-FED/<version>\nJSON\n"
            if not data.startswith(self.MARS_MAGIC_HEADER):
                raise ProtocolAdapterError(
                    "Invalid MARS magic header",
                    self._protocol_info.name
                )

            # Split into lines
            lines = data.decode().split("\n")
            if len(lines) < 2:
                raise ProtocolAdapterError(
                    "Invalid MARS message format - need header and JSON lines",
                    self._protocol_info.name
                )

            # Extract JSON from second line
            json_str = lines[1].strip()
            if not json_str:
                raise ProtocolAdapterError(
                    "Empty JSON in MARS message",
                    self._protocol_info.name
                )

            message = json.loads(json_str)

            # Validate MARS message structure
            if "msg_type" not in message:
                raise MessageHandlerError(
                    "MARS message missing 'msg_type' field",
                    self._protocol_info.name
                )

            return message

        except json.JSONDecodeError as e:
            raise ProtocolAdapterError(
                f"JSON decode error: {e}",
                self._protocol_info.name,
                {"raw_data": data.decode() if isinstance(data, bytes) else data}
            )
        except Exception as e:
            raise ProtocolAdapterError(
                f"Deserialization error: {e}",
                self._protocol_info.name
            )

    async def handle_message(self, message: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """
        Handle MARS federation message.

        Args:
            message: MARS federation message
            session: Federation session for response routing

        Returns:
            Response message if applicable, None otherwise

        Raises:
            MessageHandlerError: If message handling fails
        """
        msg_type = message.get("msg_type")
        msg_data = message.get("data", {})
        request_id = message.get("request_id")

        if not msg_type:
            raise MessageHandlerError(
                "MARS message missing 'msg_type' field",
                self._protocol_info.name
            )

        try:
            # Route to appropriate message handler
            handler = getattr(self, f"_handle_{msg_type}", None)
            if handler is None:
                raise MessageHandlerError(
                    f"Unknown MARS message type: {msg_type}",
                    self._protocol_info.name,
                    {"msg_type": msg_type}
                )

            result = await handler(msg_data, session)

            # Return response with request_id for correlation
            if result is not None and request_id:
                result["request_id"] = request_id

            return result

        except Exception as e:
            raise MessageHandlerError(
                f"Error handling {msg_type}: {e}",
                self._protocol_info.name,
                {"msg_type": msg_type, "error": str(e)}
            )

    # MARS Message Handlers

    async def _handle_node_handshake(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle node_handshake - Node identity and capability exchange.

        Args:
            data: {
                "node_id": "remote_node_id",
                "version": "1.0.0",
                "agents": [...],
                "capabilities": [...]
            }

        Returns:
            Local node handshake response
        """
        node_id = data.get("node_id")
        version = data.get("version")
        remote_agents = data.get("agents", [])
        remote_capabilities = data.get("capabilities", [])

        if not node_id:
            raise MessageHandlerError("node_handshake missing 'node_id' field")

        if self._node_registry is None:
            raise MessageHandlerError("Node registry not available")

        # Register remote node
        await self._node_registry.register_node(
            node_id,
            version,
            remote_capabilities,
            session
        )

        # Create virtual agents for remote agents
        for agent_info in remote_agents:
            await self.server.create_virtual_agent(
                agent_info["agent_id"],
                node_id,
                agent_info
            )

        # Return handshake response
        return {
            "msg_type": self.MSG_NODE_HANDSHAKE,
            "data": {
                "node_id": self.server.node_id,
                "version": self.server.version,
                "agents": await self._get_local_agents(),
                "capabilities": [
                    "a2a",
                    "mcp",
                    "ag_ui",
                    "artifact_relay"
                ]
            }
        }

    async def _handle_agent_announcement(self, data: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """
        Handle agent_announcement - Remote agent lifecycle events.

        Args:
            data: {
                "agent_id": "...",
                "event": "spawn" | "despawn",
                "agent_info": {...}
            }

        Returns:
            Acknowledgment or None
        """
        node_id = data.get("node_id")
        agent_id = data.get("agent_id")
        event = data.get("event")
        agent_info = data.get("agent_info", {})

        if not agent_id or not event:
            raise MessageHandlerError("agent_announcement missing required fields")

        if event == "spawn":
            # Create virtual agent
            await self.server.create_virtual_agent(agent_id, node_id, agent_info)
        elif event == "despawn":
            # Remove virtual agent
            await self.server.remove_virtual_agent(agent_id)
        else:
            raise MessageHandlerError(f"Unknown agent event: {event}")

        return None  # No response needed for announcements

    async def _handle_federated_message(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle federated_message - Message to remote agent.

        Args:
            data: {
                "source_agent": "...",
                "target_agent": "...",
                "payload": {...},
                "timestamp": 1234567890
            }

        Returns:
            Federated response
        """
        source_agent = data.get("source_agent")
        target_agent = data.get("target_agent")
        payload = data.get("payload")
        timestamp = data.get("timestamp")

        if not source_agent or not target_agent or not payload:
            raise MessageHandlerError("federated_message missing required fields")

        # Route message to target agent
        response = await self.server.route_federated_message(
            source_agent,
            target_agent,
            payload,
            timestamp
        )

        return {
            "msg_type": self.MSG_FEDERATED_RESPONSE,
            "data": {
                "source_agent": target_agent,
                "target_agent": source_agent,
                "payload": response,
                "timestamp": int(timestamp * 1000)  # Convert to milliseconds
            }
        }

    async def _handle_federated_response(self, data: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """
        Handle federated_response - Response from remote agent.

        Args:
            data: {
                "source_agent": "...",
                "target_agent": "...",
                "payload": {...},
                "timestamp": 1234567890
            }

        Returns:
            None (response is delivered to waiting agent)
        """
        source_agent = data.get("source_agent")
        target_agent = data.get("target_agent")
        payload = data.get("payload")

        if not source_agent or not target_agent or not payload:
            raise MessageHandlerError("federated_response missing required fields")

        # Deliver response to waiting agent
        await self.server.deliver_federated_response(
            source_agent,
            target_agent,
            payload
        )

        return None  # No response needed

    async def _handle_artifact_transfer(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle artifact_transfer - Cross-node artifact sharing.

        Args:
            data: {
                "artifact_id": "...",
                "source_node": "...",
                "content": "...",
                "tags": [...]
            }

        Returns:
            Transfer acknowledgment
        """
        artifact_id = data.get("artifact_id")
        source_node = data.get("source_node")
        content = data.get("content")
        tags = data.get("tags", [])

        if not artifact_id or not content:
            raise MessageHandlerError("artifact_transfer missing required fields")

        # Store artifact from remote node
        await self.server.store_federated_artifact(
            artifact_id,
            source_node,
            content,
            tags
        )

        return {
            "msg_type": "artifact_ack",
            "data": {
                "artifact_id": artifact_id,
                "status": "received"
            }
        }

    async def _handle_keepalive(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle keepalive - Connection health monitoring.

        Args:
            data: {
                "timestamp": 1234567890,
                "node_id": "..."
            }

        Returns:
            Keepalive response
        """
        node_id = data.get("node_id")
        timestamp = data.get("timestamp")

        # Update node last seen time
        if node_id:
            if self._node_registry is None:
                raise MessageHandlerError("Node registry not available")
            await self._node_registry.update_last_seen(node_id)

        return {
            "msg_type": "keepalive_ack",
            "data": {
                "timestamp": int(timestamp * 1000),
                "node_id": self.server.node_id
            }
        }

    # Helper Methods

    async def _get_local_agents(self) -> List[Dict[str, Any]]:
        """Get local agent list for federation"""
        agents = []
        for agent_id, agent in self.server.state.agents.items():
            agents.append({
                "agent_id": agent_id,
                "name": agent.name,
                "agent_type": agent.agent_type,
                "status": agent.status,
                "capabilities": []  # Will be populated from service discovery
            })
        return agents

    async def broadcast_agent_spawn(self, agent_id: str, agent_info: Dict[str, Any]) -> None:
        """
        Broadcast agent spawn to all federated nodes.

        Args:
            agent_id: Local agent ID
            agent_info: Agent information
        """
        announcement = {
            "msg_type": self.MSG_AGENT_ANNOUNCEMENT,
            "data": {
                "node_id": self.server.node_id,
                "agent_id": agent_id,
                "event": "spawn",
                "agent_info": agent_info
            }
        }

        await self.server.broadcast_to_federation(announcement)

    async def broadcast_agent_despawn(self, agent_id: str) -> None:
        """
        Broadcast agent despawn to all federated nodes.

        Args:
            agent_id: Local agent ID
        """
        announcement = {
            "msg_type": self.MSG_AGENT_ANNOUNCEMENT,
            "data": {
                "node_id": self.server.node_id,
                "agent_id": agent_id,
                "event": "despawn"
            }
        }

        await self.server.broadcast_to_federation(announcement)
