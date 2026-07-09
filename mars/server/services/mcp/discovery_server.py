"""Discovery MCP Server - Dynamic service discovery for LLMs.

This MCP server provides dynamic service discovery capabilities, allowing LLMs
to query available services and their capabilities at runtime. This is the
primary bootstrap service for LLMs to discover the MARS ecosystem.

Run as: python -m mars.server.services.mcp.discovery_server
"""

from __future__ import annotations

import sys
from typing import Any, Dict

from mars.server.services.mcp.builtin_server import MCPBuiltinServer


class DiscoveryMCPServer(MCPBuiltinServer):
    """Discovery Service as MCP Server.

    Provides tools for dynamic service discovery:
    - list_services: List all available services
    - get_service_info: Get detailed info about a specific service
    - discover_all_capabilities: Discover all tools/capabilities from all services
    - discover_service_capabilities: Get capabilities from a specific service
    """

    def __init__(self):
        super().__init__("discovery", "1.0.0")
        self._running = False

    def _register_handlers(self):
        """Register discovery tools."""
        # Register tools
        self.register_tool(
            name="list_services",
            description="List all available services currently registered in the system",
            input_schema={
                "type": "object",
                "properties": {
                    "service_type": {
                        "type": "string",
                        "description": "Optional filter by service type (llm, mcp, a2a, builtin)",
                        "enum": ["llm", "mcp", "a2a", "builtin"]
                    }
                }
            },
            handler=self._list_services
        )

        self.register_tool(
            name="get_service_info",
            description="Get detailed information about a specific service including its type, capabilities, and status",
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Name of the service to query"
                    }
                },
                "required": ["service_name"]
            },
            handler=self._get_service_info
        )

        self.register_tool(
            name="discover_all_capabilities",
            description="Discover all tools and capabilities available from all registered services",
            input_schema={
                "type": "object",
                "properties": {
                    "service_type": {
                        "type": "string",
                        "description": "Optional filter by service type (llm, mcp, a2a, builtin)"
                    },
                    "name_pattern": {
                        "type": "string",
                        "description": "Optional filter by tool/service name pattern"
                    }
                }
            },
            handler=self._discover_all_capabilities
        )

        self.register_tool(
            name="discover_service_capabilities",
            description="Get all capabilities/tools from a specific service",
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Name of the service to query"
                    }
                },
                "required": ["service_name"]
            },
            handler=self._discover_service_capabilities
        )

    async def initialize(self):
        """Start the Discovery Service."""
        self._running = True
        print("Discovery MCP Server initialized", file=sys.stderr)

    async def shutdown(self):
        """Stop the Discovery Service."""
        self._running = False
        print("Discovery MCP Server shutting down", file=sys.stderr)

    # Tool handlers

    async def _list_services(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List all available services."""
        from mars.server.services.registry import list_services, discover_capabilities_by_filter

        service_type = arguments.get("service_type")

        services = list_services()
        if service_type:
            services = discover_capabilities_by_filter(service_type=service_type)
            service_names = [s["service_id"] for s in services]
        else:
            service_names = services

        return {
            "services": service_names,
            "total": len(service_names),
            "message": f"Found {len(service_names)} services" + (f" of type {service_type}" if service_type else "")
        }

    async def _get_service_info(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed information about a specific service."""
        from mars.server.services.registry import get_service_info, list_services, get_service

        service_name = arguments.get("service_name")

        info = get_service_info(service_name)
        if not info:
            return {
                "error": f"Service '{service_name}' not found",
                "available_services": list_services()
            }

        # Try to instantiate the service to get real-time capabilities
        try:
            service = get_service(service_name)

            return {
                "name": service_name,
                "type": info["type"],
                "display_name": getattr(service, 'display_name', service_name),
                "running": getattr(service, 'is_running', False),
                "capabilities": [
                    {
                        "name": cap.name,
                        "description": cap.description
                    }
                    for cap in service.capabilities
                ],
                "capability_count": len(service.capabilities),
                "module": info["module"],
                "default": info["default"]
            }
        except Exception as e:
            return {
                "name": service_name,
                "type": info["type"],
                "error": f"Could not instantiate service: {str(e)}",
                "module": info["module"],
                "default": info["default"]
            }

    async def _discover_all_capabilities(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Discover all capabilities from all services."""
        from mars.server.services.registry import discover_capabilities_by_filter

        service_type = arguments.get("service_type")
        name_pattern = arguments.get("name_pattern")

        capabilities = discover_capabilities_by_filter(
            service_type=service_type,
            name_pattern=name_pattern
        )

        # Group capabilities by service for better organization
        by_service: Dict[str, list[Dict]] = {}
        for cap in capabilities:
            service_id = cap["service_id"]
            if service_id not in by_service:
                by_service[service_id] = []
            by_service[service_id].append({
                "name": cap["name"],
                "description": cap["description"],
                "service_type": cap["service_type"]
            })

        return {
            "total_capabilities": len(capabilities),
            "services_with_capabilities": len(by_service),
            "capabilities_by_service": by_service,
            "message": f"Discovered {len(capabilities)} capabilities across {len(by_service)} services"
        }

    async def _discover_service_capabilities(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get capabilities from a specific service."""
        from mars.server.services.registry import get_service

        service_name = arguments.get("service_name")

        try:
            service = get_service(service_name)
            capabilities = [
                {
                    "name": cap.name,
                    "description": cap.description,
                    "input_schema": cap.input_schema
                }
                for cap in service.capabilities
            ]

            return {
                "service": service_name,
                "service_type": service.service_type,
                "capabilities": capabilities,
                "capability_count": len(capabilities),
                "message": f"Service '{service_name}' has {len(capabilities)} capabilities"
            }
        except Exception as e:
            return {
                "error": f"Could not query service '{service_name}': {str(e)}",
                "service": service_name
            }


def main():
    """Main entry point for the Discovery MCP Server."""
    server = DiscoveryMCPServer()
    server.start()


if __name__ == "__main__":
    main()
