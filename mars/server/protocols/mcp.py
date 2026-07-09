"""
MCP Protocol Adapter

Implements the MCP (Model Context Protocol) for service agent communication.
MCP is Anthropic's open-source standard for connecting AI agents to external systems.
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


class MCPProtocolAdapter(ProtocolAdapter):
    """
    MCP Protocol Adapter

    Implements MCP stdio protocol for service agent communication:
    - initialize - Protocol handshake
    - tools/list - List available tools
    - tools/call - Invoke tool
    - resources/list - List available resources
    - resources/read - Read resource content
    - prompts/list - List available prompts
    - prompts/get - Get prompt content

    MCP Concepts:
    - Tools - Executable functions with input schemas
    - Resources - Data sources (files, memory, etc.)
    - Prompts - Reusable prompt templates
    - Sessions - Persistent connections with context sharing
    """

    # MCP protocol identifiers
    MCP_PROTOCOL_VERSION = "2024-11-05"
    MCP_MAGIC_HEADER = b"MCP-STDIO/"

    def __init__(self, server: Any):
        super().__init__(server)
        # Initialize registries from server if available
        self._tool_registry = getattr(server, '_tool_registry', None)
        self._resource_registry = getattr(server, '_resource_registry', None)
        self._prompt_registry = getattr(server, '_prompt_registry', None)
        self._protocol_info = ProtocolInfo(
            name="MCP",
            version=self.MCP_PROTOCOL_VERSION,
            protocol_type=ProtocolType.MCP,
            capabilities=[
                "initialize",
                "tools/list",
                "tools/call",
                "resources/list",
                "resources/read",
                "prompts/list",
                "prompts/get"
            ],
            description="Model Context Protocol for service communication"
        )

    def get_protocol_info(self) -> ProtocolInfo:
        """Return MCP protocol metadata"""
        return self._protocol_info

    def supports_protocol(self, protocol_identifier: Any) -> bool:
        """
        Check if data is MCP stdio message.

        Args:
            protocol_identifier: Raw bytes or message dict to check

        Returns:
            True if data is MCP format
        """
        if isinstance(protocol_identifier, bytes):
            return protocol_identifier.startswith(self.MCP_MAGIC_HEADER)
        elif isinstance(protocol_identifier, dict):
            # MCP messages have a "jsonrpc" field but don't require version check
            return "jsonrpc" in protocol_identifier and "method" in protocol_identifier
        return False

    async def serialize_message(self, message: Dict[str, Any]) -> bytes:
        """
        Serialize message to MCP stdio format.

        MCP uses JSON-RPC with a magic header for protocol detection.

        Args:
            message: Message dictionary to serialize

        Returns:
            Serialized message as bytes
        """
        # MCP format: "MCP-STDIO/<version>\nJSON-RPC\n" (JSON-RPC on separate line)
        json_str = json.dumps(message)
        return f"{self.MCP_MAGIC_HEADER.decode()}{self.MCP_PROTOCOL_VERSION}\n{json_str}\n".encode()

    async def deserialize_message(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize MCP stdio message.

        Args:
            data: Raw message bytes

        Returns:
            Deserialized JSON-RPC message dictionary

        Raises:
            ProtocolAdapterError: If deserialization fails
        """
        try:
            # Parse MCP format: "MCP-STDIO/<version>\nJSON-RPC\n"
            if not data.startswith(self.MCP_MAGIC_HEADER):
                raise ProtocolAdapterError(
                    "Invalid MCP magic header",
                    self._protocol_info.name
                )

            # Split into lines
            lines = data.decode().split("\n")
            if len(lines) < 2:
                raise ProtocolAdapterError(
                    "Invalid MCP message format - need header and JSON-RPC lines",
                    self._protocol_info.name
                )

            # Extract JSON-RPC from second line
            json_str = lines[1].strip()
            if not json_str:
                raise ProtocolAdapterError(
                    "Empty JSON-RPC in MCP message",
                    self._protocol_info.name
                )

            message = json.loads(json_str)

            # MCP messages must have "method" field
            if "method" not in message:
                raise ProtocolAdapterError(
                    "MCP message missing 'method' field",
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
        Handle MCP JSON-RPC request.

        Args:
            message: MCP JSON-RPC request message
            session: Service session for response routing

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
                "MCP request missing 'method' field",
                self._protocol_info.name
            )

        try:
            # Special handling for initialize
            if method == "initialize":
                result = await self._handle_initialize(params, session)
            else:
                # Route to appropriate method handler
                handler = getattr(self, f"_handle_{method.replace('/', '_')}", None)
                if handler is None:
                    raise MessageHandlerError(
                        f"Unknown MCP method: {method}",
                        self._protocol_info.name,
                        {"method": method}
                    )
                result = await handler(params, session)

            # Return JSON-RPC response
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:
            # Return JSON-RPC error response
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": {"method": method}
                }
            }

    # MCP Method Handlers

    async def _handle_initialize(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle initialize - Protocol handshake.

        Args:
            params: {
                "protocolVersion": "2024-11-05",
                "capabilities": {...},
                "clientInfo": {...}
            }

        Returns:
            Server capabilities and info
        """
        protocol_version = params.get("protocolVersion")
        client_info = params.get("clientInfo", {})

        # Validate protocol version
        if protocol_version != self.MCP_PROTOCOL_VERSION:
            raise MessageHandlerError(
                f"Unsupported MCP version: {protocol_version}"
            )

        # Store session capabilities
        session.mcp_capabilities = params.get("capabilities", {})
        session.client_info = client_info

        return {
            "protocolVersion": self.MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            },
            "serverInfo": {
                "name": "MARS",
                "version": "1.0.0"
            }
        }

    async def _handle_tools_list(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle tools/list - List available tools.

        Args:
            params: {}

        Returns:
            {"tools": [{"name": "...", "description": "...", "inputSchema": {...}}]}
        """
        if self._tool_registry is None:
            return {"tools": []}
        tools = await self._tool_registry.list_tools(session)
        return {"tools": tools}

    async def _handle_tools_call(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle tools/call - Invoke tool.

        Args:
            params: {
                "name": "tool_name",
                "arguments": {...}
            }

        Returns:
            Tool execution result
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise MessageHandlerError("tools/call requires 'name' parameter")

        if self._tool_registry is None:
            raise MessageHandlerError("Tool registry not available")

        result = await self._tool_registry.call_tool(tool_name, arguments, session)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result)
                }
            ],
            "isError": False
        }

    async def _handle_resources_list(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle resources/list - List available resources.

        Args:
            params: {}

        Returns:
            {"resources": [{"uri": "...", "name": "...", "description": "...", "mimeType": "..."}]}
        """
        if self._resource_registry is None:
            return {"resources": []}
        resources = await self._resource_registry.list_resources(session)
        return {"resources": resources}

    async def _handle_resources_read(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle resources/read - Read resource content.

        Args:
            params: {
                "uri": "resource_uri"
            }

        Returns:
            Resource content
        """
        uri = params.get("uri")
        if not uri:
            raise MessageHandlerError("resources/read requires 'uri' parameter")

        if self._resource_registry is None:
            raise MessageHandlerError("Resource registry not available")

        content = await self._resource_registry.read_resource(uri, session)

        return {
            "contents": [content]
        }

    async def _handle_prompts_list(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle prompts/list - List available prompts.

        Args:
            params: {}

        Returns:
            {"prompts": [{"name": "...", "description": "...", "arguments": [...]}}
        """
        if self._prompt_registry is None:
            return {"prompts": []}
        prompts = await self._prompt_registry.list_prompts(session)
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: Dict[str, Any], session: Any) -> Dict[str, Any]:
        """
        Handle prompts/get - Get prompt content.

        Args:
            params: {
                "name": "prompt_name",
                "arguments": {...}
            }

        Returns:
            Prompt content
        """
        prompt_name = params.get("name")
        arguments = params.get("arguments", {})

        if not prompt_name:
            raise MessageHandlerError("prompts/get requires 'name' parameter")

        if self._prompt_registry is None:
            raise MessageHandlerError("Prompt registry not available")

        prompt = await self._prompt_registry.get_prompt(prompt_name, arguments, session)

        return {
            "messages": [prompt]
        }

    # Service Integration

    async def register_service_tools(self, service_id: str, tools: List[Dict[str, Any]]) -> None:
        """
        Register tools from a service.

        Args:
            service_id: Service identifier
            tools: List of tool definitions
        """
        await self._tool_registry.register_service_tools(service_id, tools)

    async def unregister_service_tools(self, service_id: str) -> None:
        """
        Unregister tools from a service.

        Args:
            service_id: Service identifier
        """
        await self._tool_registry.unregister_service_tools(service_id)
