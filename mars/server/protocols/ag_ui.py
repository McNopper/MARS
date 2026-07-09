"""
AG-UI Protocol Adapter

Implements the AG-UI protocol for human CLI to agent server communication.
AG-UI is an open, lightweight, event-based protocol for agent-human interaction.
"""

import json
from typing import Any, Dict, Optional

from .base import (
    ProtocolAdapter,
    ProtocolInfo,
    ProtocolType,
    MessageHandlerError,
    ProtocolAdapterError
)


class AGUIProtocolAdapter(ProtocolAdapter):
    """
    AG-UI Protocol Adapter

    Handles AG-UI events for human-agent communication:
    - agent:hello - Initial connection handshake
    - agent:message - Bi-directional messaging
    - agent:state_update - State synchronization
    - agent:tool_call - Tool invocation
    - agent:stream_start - Begin streaming response
    - agent:stream_chunk - Streaming content
    - agent:stream_end - End streaming
    - agent:artifact - Artifact generation
    - agent:error - Error reporting
    """

    # AG-UI protocol identifier
    AG_UI_PROTOCOL_VERSION = "0.1.0"
    AG_UI_MAGIC_HEADER = b"AG-UI/"

    def __init__(self, server: Any):
        super().__init__(server)
        self._protocol_info = ProtocolInfo(
            name="AG-UI",
            version=self.AG_UI_PROTOCOL_VERSION,
            protocol_type=ProtocolType.AG_UI,
            capabilities=[
                "agent:hello",
                "agent:message",
                "agent:state_update",
                "agent:tool_call",
                "agent:stream_start",
                "agent:stream_chunk",
                "agent:stream_end",
                "agent:artifact",
                "agent:error"
            ],
            description="Agent-Human interaction protocol"
        )

    def get_protocol_info(self) -> ProtocolInfo:
        """Return AG-UI protocol metadata"""
        return self._protocol_info

    def supports_protocol(self, protocol_identifier: Any) -> bool:
        """
        Check if data starts with AG-UI magic header.

        Args:
            protocol_identifier: Raw bytes to check

        Returns:
            True if data starts with AG-UI header
        """
        if isinstance(protocol_identifier, bytes):
            return protocol_identifier.startswith(self.AG_UI_MAGIC_HEADER)
        return False

    async def serialize_message(self, message: Dict[str, Any]) -> bytes:
        """
        Serialize message to AG-UI format.

        AG-UI uses JSON with a magic header for protocol detection.
        Format: "AG-UI/<version>\nJSON\n" (JSON on separate line to avoid space conflicts)

        Args:
            message: Message dictionary to serialize

        Returns:
            Serialized message as bytes
        """
        # AG-UI format: "AG-UI/<version>\nJSON\n" (JSON on separate line)
        json_str = json.dumps(message)
        return f"{self.AG_UI_MAGIC_HEADER.decode()}{self.AG_UI_PROTOCOL_VERSION}\n{json_str}\n".encode()

    async def deserialize_message(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize AG-UI message.

        Args:
            data: Raw message bytes

        Returns:
            Deserialized message dictionary

        Raises:
            ProtocolAdapterError: If deserialization fails
        """
        try:
            # Parse AG-UI format: "AG-UI/<version>\nJSON\n"
            if not data.startswith(self.AG_UI_MAGIC_HEADER):
                raise ProtocolAdapterError(
                    "Invalid AG-UI magic header",
                    self._protocol_info.name
                )

            # Split into lines
            lines = data.decode().split("\n")
            if len(lines) < 2:
                raise ProtocolAdapterError(
                    "Invalid AG-UI message format - need header and JSON lines",
                    self._protocol_info.name
                )

            # Extract JSON from second line
            json_str = lines[1].strip()
            if not json_str:
                raise ProtocolAdapterError(
                    "Empty JSON in AG-UI message",
                    self._protocol_info.name
                )

            message = json.loads(json_str)

            # Validate AG-UI event structure
            if "event" not in message:
                raise MessageHandlerError(
                    "AG-UI message missing 'event' field",
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
        Handle AG-UI event message.

        Args:
            message: AG-UI event message
            session: Client session for response routing

        Returns:
            Response event if applicable, None otherwise

        Raises:
            MessageHandlerError: If event handling fails
        """
        event_type = message.get("event")
        event_data = message.get("data", {})

        # Route to appropriate event handler
        handler = getattr(self, f"_handle_{event_type.replace(':', '_')}", None)
        if handler is None:
            raise MessageHandlerError(
                f"Unknown AG-UI event type: {event_type}",
                self._protocol_info.name,
                {"event_type": event_type}
            )

        try:
            return await handler(event_data, session)
        except Exception as e:
            raise MessageHandlerError(
                f"Error handling {event_type}: {e}",
                self._protocol_info.name,
                {"event_type": event_type, "error": str(e)}
            )

    # AG-UI Event Handlers

    async def _handle_agent_hello(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """Handle agent:hello event - initial connection handshake"""
        # Send welcome response with agent roster and capabilities
        return {
            "event": "agent:welcome",
            "data": {
                "server_version": self.server.version,
                "protocol_version": self.AG_UI_PROTOCOL_VERSION,
                "agents": await self._get_agent_roster(),
                "capabilities": self._protocol_info.capabilities
            }
        }

    async def _handle_agent_message(self, data: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """Handle agent:message event - bi-directional messaging"""
        target = data.get("target")
        message = data.get("message")

        if not target or not message:
            raise MessageHandlerError(
                "agent:message requires 'target' and 'message' fields",
                self._protocol_info.name
            )

        # Route message through server's message routing system
        # This will be connected to the existing MARSServer routing
        response = await self.server.route_message_to_agent(target, message, session)

        if response:
            return {
                "event": "agent:message",
                "data": {
                    "from": target,
                    "message": response
                }
            }
        return None

    async def _handle_agent_state_update(self, data: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """Handle agent:state_update event - state synchronization"""
        # Broadcast state update to all connected clients
        await self.server.broadcast_state_update(data)
        return None

    async def _handle_agent_tool_call(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """Handle agent:tool_call event - tool invocation"""
        tool_name = data.get("tool")
        tool_args = data.get("args", {})

        if not tool_name:
            raise MessageHandlerError(
                "agent:tool_call requires 'tool' field",
                self._protocol_info.name
            )

        # Route to service via MCP
        result = await self.server.call_tool(tool_name, tool_args)

        return {
            "event": "agent:tool_result",
            "data": {
                "tool": tool_name,
                "result": result
            }
        }

    async def _handle_agent_stream_start(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """Handle agent:stream_start event - begin streaming response"""
        return {
            "event": "agent:stream_start",
            "data": {
                "stream_id": data.get("stream_id"),
                "metadata": data.get("metadata", {})
            }
        }

    async def _handle_agent_stream_chunk(self, data: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """Handle agent:stream_chunk event - streaming content"""
        # Forward stream chunk to client
        await session.send_stream_chunk(data.get("stream_id"), data.get("chunk"))
        return None

    async def _handle_agent_stream_end(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """Handle agent:stream_end event - end streaming"""
        return {
            "event": "agent:stream_end",
            "data": {
                "stream_id": data.get("stream_id"),
                "final": data.get("final", {})
            }
        }

    async def _handle_agent_artifact(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """Handle agent:artifact event - artifact generation"""
        artifact_id = data.get("artifact_id")
        artifact_data = data.get("artifact")

        if not artifact_id or not artifact_data:
            raise MessageHandlerError(
                "agent:artifact requires 'artifact_id' and 'artifact' fields",
                self._protocol_info.name
            )

        # Store artifact and notify clients
        await self.server.store_artifact(artifact_id, artifact_data)

        return {
            "event": "agent:artifact_ack",
            "data": {
                "artifact_id": artifact_id,
                "status": "stored"
            }
        }

    async def _handle_agent_error(self, data: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """Handle agent:error event - error reporting"""
        # Log error and broadcast to monitoring systems
        await self.server.handle_error(data.get("error", {}))
        return None

    # Helper Methods

    async def _get_agent_roster(self) -> Dict[str, Any]:
        """Get current agent roster"""
        # This will be connected to MARSState.agents
        return {
            agent_id: {
                "name": agent.name,
                "type": agent.agent_type,
                "status": agent.status
            }
            for agent_id, agent in self.server.state.agents.items()
        }
