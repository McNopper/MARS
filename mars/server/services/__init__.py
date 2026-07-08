"""MARS Services - unified service registry."""

from mars.server.services.base import Service, ServiceCapability, BuiltinService
from mars.server.services.registry import (
    get_service,
    list_services,
    get_service_info,
    discover_all_capabilities,
    discover_capabilities_by_filter,
    get_tool_schema_for_llm,
)

__all__ = [
    "Service",
    "ServiceCapability",
    "BuiltinService",
    "get_service",
    "list_services",
    "get_service_info",
    "discover_all_capabilities",
    "discover_capabilities_by_filter",
    "get_tool_schema_for_llm",
]
