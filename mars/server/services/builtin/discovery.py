"""Discovery Service/Agent - Dynamic service discovery for LLMs.

This service allows LLMs to dynamically discover available services and their
capabilities at runtime. Services can appear and disappear during operation,
and the Discovery Service provides real-time service discovery.

This is the primary service communicated to LLMs at bootstrap, enabling
LLMs to discover what other tools and services are available dynamically.
"""
from __future__ import annotations

from typing import Any

from mars.server.services.base import BuiltinService, ServiceCapability


class DiscoveryService(BuiltinService):
    """Discovery Service/Agent for dynamic service discovery.

    This service acts as the main discovery interface for LLMs, allowing
    them to query available services and their capabilities at runtime.
    Services can be dynamically registered/unregistered, and this service
    provides real-time discovery capabilities.

    Tools exposed to LLMs:
    - list_services: List all available services
    - get_service_info: Get detailed info about a specific service
    - discover_all_capabilities: Discover all tools/capabilities from all services
    - discover_service_capabilities: Get capabilities from a specific service
    """

    def __init__(self) -> None:
        self._service_id = "discovery"
        self._running = False

    @property
    def service_id(self) -> str:
        return self._service_id

    @property
    def display_name(self) -> str:
        return "Discovery Service"

    @property
    def capabilities(self) -> list[ServiceCapability]:
        """Expose discovery tools as capabilities."""
        return [
            ServiceCapability(
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
                }
            ),
            ServiceCapability(
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
                }
            ),
            ServiceCapability(
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
                }
            ),
            ServiceCapability(
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
                }
            ),
        ]

    async def initialize(self) -> None:
        """Start the Discovery Service."""
        self._running = True

    async def shutdown(self) -> None:
        """Stop the Discovery Service."""
        self._running = False

    async def call_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a discovery tool."""
        if tool_name == "list_services":
            return await self._list_services(**kwargs)
        elif tool_name == "get_service_info":
            return await self._get_service_info(**kwargs)
        elif tool_name == "discover_all_capabilities":
            return await self._discover_all_capabilities(**kwargs)
        elif tool_name == "discover_service_capabilities":
            return await self._discover_service_capabilities(**kwargs)
        else:
            return f"Unknown discovery tool: {tool_name}"

    async def _list_services(self, service_type: str | None = None, **_: Any) -> dict[str, Any]:
        """List all available services."""
        from mars.server.services.registry import list_services

        services = list_services()
        if service_type:
            from mars.server.services.registry import discover_capabilities_by_filter
            services = discover_capabilities_by_filter(service_type=service_type)
            service_names = [s["service_id"] for s in services]
        else:
            service_names = services

        return {
            "services": service_names,
            "total": len(service_names),
            "message": f"Found {len(service_names)} services" + (f" of type {service_type}" if service_type else "")
        }

    async def _get_service_info(self, service_name: str, **_: Any) -> dict[str, Any]:
        """Get detailed information about a specific service."""
        from mars.server.services.registry import get_service_info, list_services

        info = get_service_info(service_name)
        if not info:
            return {
                "error": f"Service '{service_name}' not found",
                "available_services": list_services()
            }

        # Try to instantiate the service to get real-time capabilities
        try:
            from mars.server.services.registry import get_service
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

    async def _discover_all_capabilities(
        self,
        service_type: str | None = None,
        name_pattern: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Discover all capabilities from all services."""
        from mars.server.services.registry import discover_capabilities_by_filter

        capabilities = discover_capabilities_by_filter(
            service_type=service_type,
            name_pattern=name_pattern
        )

        # Group capabilities by service for better organization
        by_service: dict[str, list[dict]] = {}
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

    async def _discover_service_capabilities(self, service_name: str, **_: Any) -> dict[str, Any]:
        """Get capabilities from a specific service."""
        from mars.server.services.registry import get_service

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