"""
A2A Protocol Adapter

Implements the A2A (Agent-to-Agent) protocol for agent communication.
A2A is an open protocol enabling communication and interoperability between agents.
"""

import json
from typing import Any, Dict, Optional, List
from uuid import uuid4

from .base import (
    ProtocolAdapter,
    ProtocolInfo,
    ProtocolType,
    MessageHandlerError,
    ProtocolAdapterError
)


class A2AProtocolAdapter(ProtocolAdapter):
    """
    A2A Protocol Adapter

    Implements A2A JSON-RPC 2.0 protocol for agent-to-agent communication:
    - message/send - Send messages and create tasks
    - tasks/get - Retrieve task status
    - tasks/cancel - Cancel running tasks
    - message/stream - SSE streaming for real-time updates
    - tasks/resubscribe - Resume streaming connections

    A2A Concepts:
    - Agent Cards - JSON metadata for agent discovery
    - Tasks - Stateful work units with lifecycle
    - Messages - Role-based communication (user/agent)
    - Parts - Content units (TextPart, FilePart, DataPart)
    - Artifacts - Tangible outputs
    """

    # A2A protocol identifiers
    A2A_PROTOCOL_VERSION = "0.3.0"
    A2A_JSONRPC_VERSION = "2.0"
    A2A_MAGIC_HEADER = b"A2A-JSONRPC/"

    # A2A task lifecycle states
    TASK_STATES = [
        "submitted",
        "working",
        "input_required",
        "auth_required",
        "completed",
        "canceled",
        "rejected",
        "failed"
    ]

    def __init__(self, server: Any):
        super().__init__(server)
        # Initialize managers from server if available
        self._task_manager = getattr(server, '_task_manager', None)
        self._agent_card_manager = getattr(server, '_agent_card_manager', None)
        self._protocol_info = ProtocolInfo(
            name="A2A",
            version=self.A2A_PROTOCOL_VERSION,
            protocol_type=ProtocolType.A2A,
            capabilities=[
                "message/send",
                "tasks/get",
                "tasks/cancel",
                "message/stream",
                "tasks/resubscribe"
            ],
            description="Agent-to-Agent communication protocol"
        )

    def get_protocol_info(self) -> ProtocolInfo:
        """Return A2A protocol metadata"""
        return self._protocol_info

    def supports_protocol(self, protocol_identifier: Any) -> bool:
        """
        Check if data is A2A JSON-RPC message.

        Args:
            protocol_identifier: Raw bytes or message dict to check

        Returns:
            True if data is A2A JSON-RPC format
        """
        if isinstance(protocol_identifier, bytes):
            return protocol_identifier.startswith(self.A2A_MAGIC_HEADER)
        elif isinstance(protocol_identifier, dict):
            return (
                "jsonrpc" in protocol_identifier and
                protocol_identifier.get("jsonrpc") == self.A2A_JSONRPC_VERSION
            )
        return False

    async def serialize_message(self, message: Dict[str, Any]) -> bytes:
        """
        Serialize message to A2A JSON-RPC format.

        A2A uses JSON-RPC 2.0 with a magic header for protocol detection.

        Args:
            message: Message dictionary to serialize

        Returns:
            Serialized message as bytes
        """
        # A2A format: "A2A-JSONRPC/<version>\nJSON-RPC\n" (JSON on separate line)
        json_str = json.dumps(message)
        return f"{self.A2A_MAGIC_HEADER.decode()}{self.A2A_PROTOCOL_VERSION}\n{json_str}\n".encode()

    async def deserialize_message(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize A2A JSON-RPC message.

        Args:
            data: Raw message bytes

        Returns:
            Deserialized JSON-RPC message dictionary

        Raises:
            ProtocolAdapterError: If deserialization fails
        """
        try:
            # Parse A2A format: "A2A-JSONRPC/<version>\nJSON-RPC\n"
            if not data.startswith(self.A2A_MAGIC_HEADER):
                raise ProtocolAdapterError(
                    "Invalid A2A magic header",
                    self._protocol_info.name
                )

            # Split into lines
            lines = data.decode().split("\n")
            if len(lines) < 2:
                raise ProtocolAdapterError(
                    "Invalid A2A message format - need header and JSON-RPC lines",
                    self._protocol_info.name
                )

            # Extract JSON-RPC from second line
            json_str = lines[1].strip()
            if not json_str:
                raise ProtocolAdapterError(
                    "Empty JSON-RPC in A2A message",
                    self._protocol_info.name
                )

            message = json.loads(json_str)

            # Validate JSON-RPC 2.0 structure
            if "jsonrpc" not in message or message.get("jsonrpc") != self.A2A_JSONRPC_VERSION:
                raise ProtocolAdapterError(
                    "Invalid JSON-RPC version",
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
        Handle A2A JSON-RPC request.

        Args:
            message: A2A JSON-RPC request message
            session: Agent session for response routing

        Returns:
            JSON-RPC response message

        Raises:
            MessageHandlerError: If request handling fails
        """
        method = message.get("method")
        params = message.get("params", {})
        request_id = message.get("id")

        if not method:
            raise MessageHandlerError(
                "A2A request missing 'method' field",
                self._protocol_info.name
            )

        try:
            # Route to appropriate method handler
            handler = getattr(self, f"_handle_{method.replace('/', '_')}", None)
            if handler is None:
                raise MessageHandlerError(
                    f"Unknown A2A method: {method}",
                    self._protocol_info.name,
                    {"method": method}
                )

            result = await handler(params, session)

            # Return JSON-RPC response
            return {
                "jsonrpc": self.A2A_JSONRPC_VERSION,
                "id": request_id,
                "result": result
            }

        except Exception as e:
            # Return JSON-RPC error response
            return {
                "jsonrpc": self.A2A_JSONRPC_VERSION,
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": str(e),
                    "data": {"method": method}
                }
            }

    # A2A Method Handlers

    async def _handle_message_send(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle message/send - Send message and create task.

        Args:
            params: {
                "message": {
                    "role": "user" | "agent",
                    "parts": [{"kind": "text", "text": "..."}]
                }
            }

        Returns:
            {"task_id": "...", "status": "submitted"}
        """
        message = params.get("message")
        if not message:
            raise MessageHandlerError("message/send requires 'message' parameter")

        # Create A2A task
        task_id = str(uuid4())

        if self._task_manager is None:
            raise MessageHandlerError("Task manager not available")

        task = await self._task_manager.create_task(task_id, message)

        # Route message to target agent
        target_agent = message.get("target") or session.agent_id
        await self.server.route_a2a_message(target_agent, message, task_id)

        return {
            "task_id": task_id,
            "status": task.status,
            "created_at": task.created_at.isoformat()
        }

    async def _handle_tasks_get(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle tasks/get - Retrieve task status.

        Args:
            params: {"task_id": "..."}

        Returns:
            Task status and result
        """
        task_id = params.get("task_id")
        if not task_id:
            raise MessageHandlerError("tasks/get requires 'task_id' parameter")

        if self._task_manager is None:
            raise MessageHandlerError("Task manager not available")

        task = await self._task_manager.get_task(task_id)
        if not task:
            raise MessageHandlerError(f"Task not found: {task_id}")

        return {
            "task_id": task_id,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat() if task.updated_at else None
        }

    async def _handle_tasks_cancel(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle tasks/cancel - Cancel running task.

        Args:
            params: {"task_id": "..."}

        Returns:
            {"task_id": "...", "status": "canceled"}
        """
        task_id = params.get("task_id")
        if not task_id:
            raise MessageHandlerError("tasks/cancel requires 'task_id' parameter")

        if self._task_manager is None:
            raise MessageHandlerError("Task manager not available")

        task = await self._task_manager.cancel_task(task_id)
        if not task:
            raise MessageHandlerError(f"Task not found: {task_id}")

        return {
            "task_id": task_id,
            "status": task.status,
            "canceled_at": task.updated_at.isoformat() if task.updated_at else None
        }

    async def _handle_message_stream(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle message/stream - SSE streaming for real-time updates.

        Args:
            params: {"task_id": "...", "resubscribe": false}

        Returns:
            Stream connection info
        """
        task_id = params.get("task_id")
        if not task_id:
            raise MessageHandlerError("message/stream requires 'task_id' parameter")

        if self._task_manager is None:
            raise MessageHandlerError("Task manager not available")

        # Set up SSE stream for task updates
        stream_url = await self._task_manager.create_task_stream(task_id, session)

        return {
            "task_id": task_id,
            "stream_url": stream_url,
            "status": "streaming"
        }

    async def _handle_tasks_resubscribe(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle tasks/resubscribe - Resume streaming connection.

        Args:
            params: {"task_id": "...", "stream_id": "..."}

        Returns:
            Resubscribed stream info
        """
        task_id = params.get("task_id")
        stream_id = params.get("stream_id")

        if not task_id or not stream_id:
            raise MessageHandlerError("tasks/resubscribe requires 'task_id' and 'stream_id' parameters")

        if self._task_manager is None:
            raise MessageHandlerError("Task manager not available")

        # Resume existing stream
        stream_url = await self._task_manager.resubscribe_stream(task_id, stream_id, session)

        return {
            "task_id": task_id,
            "stream_id": stream_id,
            "stream_url": stream_url,
            "status": "resubscribed"
        }

    # Agent Card Methods

    async def get_agent_card(self, agent_id: str) -> Dict[str, Any]:
        """
        Get Agent Card for agent.

        Args:
            agent_id: Agent identifier

        Returns:
            Agent Card JSON
        """
        agent = self.server.state.agents.get(agent_id)
        if not agent:
            raise MessageHandlerError(f"Agent not found: {agent_id}")

        return {
            "agent_id": agent_id,
            "name": agent.name,
            "version": "1.0.0",
            "description": f"{agent.agent_type} agent",
            "capabilities": await self._get_agent_capabilities(agent_id),
            "endpoints": {
                "a2a": f"a2a://{agent_id}@mars.local",
                "tasks": f"/tasks/{agent_id}"
            },
            "authentication": "none",  # Will be enhanced later
            "metadata": {
                "agent_type": agent.agent_type,
                "status": agent.status
            }
        }

    async def _get_agent_capabilities(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get agent capabilities (skills, tools, etc.)"""
        # This will be connected to the service discovery system
        return []
