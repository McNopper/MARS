"""
MCP Tool Registry

Manages MCP tool registration, discovery, and invocation for service communication.
All services in MARS expose their capabilities via MCP tools.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4


@dataclass
class MCPTool:
    """MCP Tool representation"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    service_id: str
    handler: Optional[Callable] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert tool to MCP tool format"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema
        }


class MCPToolRegistry:
    """
    Registry for MCP tools across all services.

    Provides:
    - Tool registration per service
    - Cross-service tool discovery
    - Tool invocation routing
    - Service lifecycle management
    """

    def __init__(self):
        self._tools: Dict[str, List[MCPTool]] = {}  # service_id -> [tools]
        self._tool_index: Dict[str, MCPTool] = {}  # tool_name -> MCPTool
        self._handlers: Dict[str, Callable] = {}  # tool_name -> handler
        self._lock = asyncio.Lock()

    async def register_service_tools(
        self,
        service_id: str,
        tools: List[Dict[str, Any]],
        handlers: Optional[Dict[str, Callable]] = None
    ) -> None:
        """
        Register tools for a service.

        Args:
            service_id: Service identifier
            tools: List of tool definitions
            handlers: Optional mapping of tool names to handler functions
        """
        async with self._lock:
            # Remove existing tools for this service
            await self.unregister_service_tools(service_id)

            # Register new tools
            mcp_tools = []
            for tool_def in tools:
                tool_name = tool_def.get("name")
                if not tool_name:
                    continue

                tool = MCPTool(
                    name=tool_name,
                    description=tool_def.get("description", ""),
                    input_schema=tool_def.get("input_schema", {}),
                    service_id=service_id,
                    handler=handlers.get(tool_name) if handlers else None
                )

                mcp_tools.append(tool)
                self._tool_index[tool_name] = tool

                if tool.handler:
                    self._handlers[tool_name] = tool.handler

            self._tools[service_id] = mcp_tools

    async def unregister_service_tools(self, service_id: str) -> None:
        """
        Unregister all tools for a service.

        Args:
            service_id: Service identifier
        """
        async with self._lock:
            # Remove tools from index
            if service_id in self._tools:
                for tool in self._tools[service_id]:
                    self._tool_index.pop(tool.name, None)
                    self._handlers.pop(tool.name, None)

            # Remove service
            self._tools.pop(service_id, None)

    async def list_tools(self, service_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List available tools.

        Args:
            service_id: Optional service ID to filter by

        Returns:
            List of tool definitions in MCP format
        """
        async with self._lock:
            if service_id:
                tools = self._tools.get(service_id, [])
                return [tool.to_dict() for tool in tools]

            # List all tools
            all_tools = []
            for tools in self._tools.values():
                all_tools.extend(tools)

            return [tool.to_dict() for tool in all_tools]

    async def get_tool(self, tool_name: str) -> Optional[MCPTool]:
        """
        Get tool by name.

        Args:
            tool_name: Tool identifier

        Returns:
            MCPTool or None if not found
        """
        return self._tool_index.get(tool_name)

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        session: Optional[Any] = None
    ) -> Any:
        """
        Invoke tool with arguments.

        Args:
            tool_name: Tool identifier
            arguments: Tool input arguments
            session: Optional session context

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found or execution fails
        """
        tool = await self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        # Call handler if available
        handler = self._handlers.get(tool_name)
        if handler:
            try:
                result = await handler(arguments, session)
                return result
            except Exception as e:
                raise ValueError(f"Tool execution error: {e}")

        # Return placeholder if no handler
        return {
            "tool": tool_name,
            "arguments": arguments,
            "status": "no_handler"
        }

    async def list_services(self) -> List[str]:
        """
        List all registered services.

        Returns:
            List of service IDs
        """
        return list(self._tools.keys())

    async def get_service_tools(self, service_id: str) -> List[MCPTool]:
        """
        Get all tools for a specific service.

        Args:
            service_id: Service identifier

        Returns:
            List of MCPTool for the service
        """
        return self._tools.get(service_id, [])

    async def find_tools_by_capability(self, capability: str) -> List[str]:
        """
        Find tools that provide a specific capability.

        Args:
            capability: Capability keyword to search for in descriptions

        Returns:
            List of tool names that match the capability
        """
        matching_tools = []

        for tool in self._tool_index.values():
            if capability.lower() in tool.description.lower():
                matching_tools.append(tool.name)

        return matching_tools

    async def validate_tool_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """
        Validate tool arguments against input schema.

        Args:
            tool_name: Tool identifier
            arguments: Arguments to validate

        Returns:
            True if arguments are valid
        """
        tool = await self.get_tool(tool_name)
        if not tool:
            return False

        # Basic validation against schema
        # TODO: Implement full JSON Schema validation
        required = tool.input_schema.get("required", [])
        properties = tool.input_schema.get("properties", {})

        # Check required fields
        for field in required:
            if field not in arguments:
                return False

        # Check argument types
        for field, value in arguments.items():
            if field in properties:
                field_schema = properties[field]
                field_type = field_schema.get("type")

                if field_type == "string" and not isinstance(value, str):
                    return False
                elif field_type == "number" and not isinstance(value, (int, float)):
                    return False
                elif field_type == "boolean" and not isinstance(value, bool):
                    return False
                elif field_type == "array" and not isinstance(value, list):
                    return False
                elif field_type == "object" and not isinstance(value, dict):
                    return False

        return True

    async def get_tool_statistics(self) -> Dict[str, Any]:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry statistics
        """
        total_tools = sum(len(tools) for tools in self._tools.values())

        service_counts = {
            service_id: len(tools)
            for service_id, tools in self._tools.items()
        }

        return {
            "total_services": len(self._tools),
            "total_tools": total_tools,
            "service_counts": service_counts,
            "tools_with_handlers": len(self._handlers)
        }

    async def export_registry_json(self) -> Dict[str, Any]:
        """
        Export registry state as JSON.

        Returns:
            Dictionary containing registry state
        """
        tools_data = {}

        for service_id, tools in self._tools.items():
            tools_data[service_id] = [tool.to_dict() for tool in tools]

        return {
            "services": list(self._tools.keys()),
            "tools": tools_data,
            "statistics": await self.get_tool_statistics()
        }

    async def cleanup_service(self, service_id: str) -> int:
        """
        Clean up tools for a service.

        Args:
            service_id: Service identifier

        Returns:
            Number of tools removed
        """
        async with self._lock:
            if service_id not in self._tools:
                return 0

            tool_count = len(self._tools[service_id])
            await self.unregister_service_tools(service_id)

            return tool_count
