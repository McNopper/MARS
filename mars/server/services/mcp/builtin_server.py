"""
MCP Builtin Server

Base server for converting builtin services to MCP stdio servers.
All MARS builtin services will run as MCP servers using this infrastructure.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional, Callable
from mcp.server import Server as MCPServer
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


class MCPBuiltinServer:
    """
    Base class for MARS builtin services to run as MCP servers.

    Provides:
    - MCP protocol handling via stdio
    - Tool registration and invocation
    - Service lifecycle management
    - Error handling and logging
    """

    def __init__(self, service_name: str, service_version: str = "1.0.0"):
        """
        Initialize MCP builtin server.

        Args:
            service_name: Name of the service
            service_version: Service version
        """
        self.service_name = service_name
        self.service_version = service_version

        # Create MCP server
        self.server = MCPServer(service_name)

        # Tool registry - initialize BEFORE registering handlers
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._tool_handlers: Dict[str, Callable] = {}

        # Register standard handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register standard MCP handlers"""
        # These will be registered by subclasses
        pass

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable
    ) -> None:
        """
        Register a tool with the MCP server.

        Args:
            name: Tool name
            description: Tool description
            input_schema: JSON Schema for tool input
            handler: Async function to handle tool calls
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema
        }
        self._tool_handlers[name] = handler

        # Register with MCP server
        @self.server.tool(name)
        async def tool_handler(arguments: Dict[str, Any]) -> List[TextContent]:
            try:
                result = await handler(arguments)
                return [TextContent(type="text", text=json.dumps(result))]
            except Exception as e:
                error_result = {
                    "error": str(e),
                    "tool": name,
                    "arguments": arguments
                }
                return [TextContent(type="text", text=json.dumps(error_result))]

    async def list_tools(self) -> List[Tool]:
        """
        List all available tools.

        Returns:
            List of Tool objects
        """
        tools = []
        for tool_def in self._tools.values():
            tools.append(
                Tool(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    inputSchema=tool_def["inputSchema"]
                )
            )
        return tools

    async def initialize(self):
        """
        Initialize the service (called on startup).

        Subclasses should override this to perform service-specific initialization.
        """
        pass

    async def shutdown(self):
        """
        Shutdown the service (called on shutdown).

        Subclasses should override this to perform service-specific cleanup.
        """
        pass

    async def run(self):
        """
        Run the MCP server.

        This starts the stdio server and handles the MCP protocol.
        """
        # Initialize service
        await self.initialize()

        # Register list_tools handler
        @self.server.list_tools()
        async def list_tools_handler() -> List[Tool]:
            return await self.list_tools()

        # Run stdio server
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )

        # Cleanup on shutdown
        await self.shutdown()

    def start(self):
        """
        Start the server (blocking call).

        This is the main entry point for running the service.
        """
        try:
            asyncio.run(self.run())
        except KeyboardInterrupt:
            print(f"\n{self.service_name} shutting down...", file=sys.stderr)
            asyncio.run(self.shutdown())
        except Exception as e:
            print(f"Error in {self.service_name}: {e}", file=sys.stderr)
            sys.exit(1)


class ServiceToolBuilder:
    """
    Helper class for building MCP tool definitions from service functions.

    Simplifies the conversion of service methods to MCP tools.
    """

    @staticmethod
    def build_tool_schema(
        function: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build MCP tool schema from function.

        Args:
            function: Function to build schema for
            name: Tool name (defaults to function name)
            description: Tool description (defaults to function docstring)

        Returns:
            Tool definition dictionary
        """
        import inspect

        tool_name = name or function.__name__
        tool_description = description or function.__doc__ or f"Tool: {tool_name}"

        # Extract function signature
        sig = inspect.signature(function)
        parameters = sig.parameters

        # Build JSON Schema
        properties = {}
        required = []

        for param_name, param in parameters.items():
            if param_name == "self":
                continue

            param_schema = ServiceToolBuilder._get_type_schema(param.annotation)
            properties[param_name] = param_schema

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        input_schema = {
            "type": "object",
            "properties": properties
        }

        if required:
            input_schema["required"] = required

        return {
            "name": tool_name,
            "description": tool_description,
            "inputSchema": input_schema
        }

    @staticmethod
    def _get_type_schema(type_hint: Any) -> Dict[str, Any]:
        """
        Get JSON Schema for a type hint.

        Args:
            type_hint: Type annotation

        Returns:
            JSON Schema for the type
        """
        if type_hint is str:
            return {"type": "string"}
        elif type_hint is int:
            return {"type": "integer"}
        elif type_hint is float:
            return {"type": "number"}
        elif type_hint is bool:
            return {"type": "boolean"}
        elif type_hint is list or type_hint is List:
            return {"type": "array", "items": {}}
        elif type_hint is dict or type_hint is Dict:
            return {"type": "object", "properties": {}}
        else:
            # Default to string for unknown types
            return {"type": "string"}

    @staticmethod
    def create_tool_wrapper(
        function: Callable,
        service_instance: Any
    ) -> Callable:
        """
        Create an async wrapper for a service function.

        Args:
            function: Service function to wrap
            service_instance: Service instance to call function on

        Returns:
            Async wrapper function
        """
        async def wrapper(arguments: Dict[str, Any]) -> Any:
            return await function(service_instance, **arguments)

        return wrapper


def create_mcp_service(
    service_class: type,
    service_name: str,
    service_version: str = "1.0.0"
) -> MCPBuiltinServer:
    """
    Create an MCP server from a service class.

    This function converts a MARS service class into an MCP server
    by registering all public methods as tools.

    Args:
        service_class: Service class to convert
        service_name: Name for the MCP service
        service_version: Service version

    Returns:
        MCPBuiltinServer instance
    """
    server = MCPBuiltinServer(service_name, service_version)

    # Create service instance
    service_instance = service_class()

    # Register all public methods as tools
    import inspect

    for name, method in inspect.getmembers(service_instance, predicate=inspect.ismethod):
        if name.startswith("_"):
            continue

        # Build tool schema
        tool_schema = ServiceToolBuilder.build_tool_schema(method)

        # Register tool
        server.register_tool(
            name=tool_schema["name"],
            description=tool_schema["description"],
            input_schema=tool_schema["inputSchema"],
            handler=ServiceToolBuilder.create_tool_wrapper(method, service_instance)
        )

    return server
