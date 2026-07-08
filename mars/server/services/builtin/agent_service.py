"""Agent Communication Service - enables agent-to-agent communication as tools.

This service allows agents to communicate with each other by exposing
communication capabilities as tools that can be discovered and called
by other agents via the unified service architecture.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


class AgentCommunicationService(BuiltinService):
    """Agent Communication Service for agent-to-agent messaging.

    This service enables agents to communicate with each other by exposing
    communication capabilities as tools. Agents can send messages to other
    agents, list available agents, and check agent status.

    Tools exposed to agents:
    - send_message: Send a message to another agent
    - list_agents: List all available agents
    - get_agent_status: Get status information about a specific agent
    - broadcast_message: Send a message to all agents (or filtered by criteria)
    """

    def __init__(self) -> None:
        self._service_id = "agent-comm"
        self._running = False
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._message_handlers: dict[str, Any] = {}

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return "Agent Communication Service"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Expose agent communication tools as capabilities."""
        return [
            ServiceCapability(
                name="send_agent_message",
                description="Send a message to a specific agent by ID",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target_agent_id": {
                            "type": "string",
                            "description": "ID of the target agent to receive the message"
                        },
                        "message": {
                            "type": "string",
                            "description": "Message content to send"
                        },
                        "message_type": {
                            "type": "string",
                            "description": "Type of message (e.g., 'request', 'response', 'notification')",
                            "default": "request"
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata to attach to the message"
                        }
                    },
                    "required": ["target_agent_id", "message"]
                }
            ),
            ServiceCapability(
                name="list_available_agents",
                description="List all available agents in the system with their capabilities",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_type": {
                            "type": "string",
                            "description": "Filter by agent type (e.g., 'LLMAgent', 'Provider')",
                            "enum": ["LLMAgent", "Provider", "HumanUser", "all"],
                            "default": "all"
                        },
                        "include_details": {
                            "type": "boolean",
                            "description": "Include detailed agent information",
                            "default": False
                        }
                    }
                }
            ),
            ServiceCapability(
                name="get_agent_info",
                description="Get detailed information about a specific agent",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "ID of the agent to query"
                        }
                    },
                    "required": ["agent_id"]
                }
            ),
            ServiceCapability(
                name="broadcast_to_agents",
                description="Send a message to multiple agents based on criteria",
                input_schema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message content to broadcast"
                        },
                        "agent_type": {
                            "type": "string",
                            "description": "Filter recipients by agent type",
                            "enum": ["LLMAgent", "Provider", "HumanUser", "all"],
                            "default": "all"
                        },
                        "exclude_sender": {
                            "type": "boolean",
                            "description": "Exclude the sender from recipients",
                            "default": True
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata to attach to the message"
                        }
                    },
                    "required": ["message"]
                }
            ),
        ]

    async def initialize(self) -> None:
        """Start the Agent Communication Service."""
        self._running = True

    async def shutdown(self) -> None:
        """Stop the Agent Communication Service."""
        self._running = False
        # Clear message handlers
        self._message_handlers.clear()

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute an agent communication tool."""
        if tool_name == "send_agent_message":
            return await self._send_agent_message(**kwargs)
        elif tool_name == "list_available_agents":
            return await self._list_available_agents(**kwargs)
        elif tool_name == "get_agent_info":
            return await self._get_agent_info(**kwargs)
        elif tool_name == "broadcast_to_agents":
            return await self._broadcast_to_agents(**kwargs)
        else:
            return f"Unknown agent communication tool: {tool_name}"

    async def _send_agent_message(
        self,
        target_agent_id: str,
        message: str,
        message_type: str = "request",
        metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a message to a specific agent."""
        # Create message envelope
        msg_envelope = {
            "type": "agent_message",
            "from_service": self._service_id,
            "to_agent": target_agent_id,
            "message": message,
            "message_type": message_type,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        # Queue the message for processing
        await self._message_queue.put(msg_envelope)

        return {
            "success": True,
            "message_id": f"msg_{datetime.now().timestamp()}",
            "target_agent": target_agent_id,
            "message_type": message_type,
            "timestamp": msg_envelope["timestamp"],
            "status": "queued",
            "note": "Message queued for delivery to agent. Actual routing depends on MARS server implementation."
        }

    async def _list_available_agents(
        self,
        agent_type: str = "all",
        include_details: bool = False
    ) -> dict[str, Any]:
        """List all available agents."""
        # This is a placeholder - in a real implementation, this would query
        # the actual MARS state for active agents
        agents = []

        # Placeholder data - in production, this would come from MARSState
        if agent_type in ["all", "LLMAgent"]:
            agents.append({
                "agent_id": "agent.anthropic@1",
                "agent_type": "LLMAgent",
                "model": "claude-opus-4-8",
                "status": "idle",
                "capabilities": ["chat", "tool_call", "reasoning"]
            })

        if agent_type in ["all", "Provider"]:
            agents.append({
                "agent_id": "svc.filesystem@1",
                "agent_type": "Provider",
                "service": "filesystem",
                "status": "running",
                "capabilities": ["read_file", "write_file", "list_directory"]
            })

        return {
            "total": len(agents),
            "filter_type": agent_type,
            "agents": agents,
            "include_details": include_details,
            "timestamp": datetime.now().isoformat()
        }

    async def _get_agent_info(self, agent_id: str) -> dict[str, Any]:
        """Get detailed information about a specific agent."""
        # Placeholder implementation
        return {
            "agent_id": agent_id,
            "found": True,
            "info": {
                "status": "active",
                "last_seen": datetime.now().isoformat(),
                "capabilities": ["communication", "collaboration"],
                "note": "This is a placeholder implementation. Real data would come from MARSState."
            }
        }

    async def _broadcast_to_agents(
        self,
        message: str,
        agent_type: str = "all",
        exclude_sender: bool = True,
        metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Broadcast a message to multiple agents."""
        broadcast_envelope = {
            "type": "agent_broadcast",
            "from_service": self._service_id,
            "message": message,
            "target_type": agent_type,
            "exclude_sender": exclude_sender,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }

        await self._message_queue.put(broadcast_envelope)

        return {
            "success": True,
            "broadcast_id": f"broadcast_{datetime.now().timestamp()}",
            "target_type": agent_type,
            "exclude_sender": exclude_sender,
            "timestamp": broadcast_envelope["timestamp"],
            "status": "queued",
            "note": "Broadcast queued for delivery. Actual routing depends on MARS server implementation."
        }

    async def get_pending_messages(self) -> list[dict[str, Any]]:
        """Get all pending messages from the queue (for MARS server integration)."""
        messages = []
        while not self._message_queue.empty():
            try:
                msg = self._message_queue.get_nowait()
                messages.append(msg)
            except asyncio.QueueEmpty:
                break
        return messages

    def register_message_handler(self, handler_name: str, handler: Any) -> None:
        """Register a custom message handler."""
        self._message_handlers[handler_name] = handler

    def unregister_message_handler(self, handler_name: str) -> None:
        """Unregister a message handler."""
        self._message_handlers.pop(handler_name, None)
