"""
Base Protocol Adapter Interface

All protocol adapters must implement this interface to ensure consistent
message handling across different protocols (AG-UI, A2A, MCP, MARS).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence
from enum import Enum


class ProtocolType(Enum):
    """Supported protocol types"""
    AG_UI = "ag_ui"
    A2A = "a2a"
    MCP = "mcp"
    MARS = "mars"


@dataclass
class ProtocolInfo:
    """Protocol metadata"""
    name: str
    version: str
    protocol_type: ProtocolType
    capabilities: Sequence[str]
    description: Optional[str] = None


class ProtocolAdapterError(Exception):
    """Base exception for protocol adapter errors"""
    def __init__(self, message: str, protocol: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.protocol = protocol
        self.details = details or {}
        super().__init__(f"[{protocol}] {message}")


class MessageHandlerError(ProtocolAdapterError):
    """Exception raised when message handling fails"""
    pass


class ProtocolNegotiationError(ProtocolAdapterError):
    """Exception raised when protocol negotiation fails"""
    pass


class ProtocolAdapter(ABC):
    """
    Abstract base class for protocol adapters.

    All protocol adapters must implement this interface to handle
    protocol-specific message serialization, deserialization, and routing.
    """

    def __init__(self, server: Any):
        """
        Initialize the protocol adapter.

        Args:
            server: The MARSServer instance this adapter belongs to
        """
        self.server = server
        self._protocol_info: Optional[ProtocolInfo] = None

    @abstractmethod
    async def handle_message(self, message: Dict[str, Any], session: Any) -> Optional[Dict[str, Any]]:
        """
        Handle incoming protocol message.

        Args:
            message: Raw protocol message (deserialized)
            session: Client/session object for response routing

        Returns:
            Response message if applicable, None otherwise

        Raises:
            MessageHandlerError: If message handling fails
        """
        pass

    @abstractmethod
    def get_protocol_info(self) -> ProtocolInfo:
        """
        Return protocol metadata.

        Returns:
            ProtocolInfo object with protocol details
        """
        pass

    @abstractmethod
    async def serialize_message(self, message: Dict[str, Any]) -> bytes:
        """
        Serialize message to protocol-specific format for transmission.

        Args:
            message: Message dictionary to serialize

        Returns:
            Serialized message as bytes
        """
        pass

    @abstractmethod
    async def deserialize_message(self, data: bytes) -> Dict[str, Any]:
        """
        Deserialize message from protocol-specific format.

        Args:
            data: Raw message bytes to deserialize

        Returns:
            Deserialized message dictionary

        Raises:
            ProtocolAdapterError: If deserialization fails
        """
        pass

    @abstractmethod
    def supports_protocol(self, protocol_identifier: Any) -> bool:
        """
        Check if this adapter supports the given protocol identifier.

        Args:
            protocol_identifier: Protocol version/magic byte/header

        Returns:
            True if this adapter supports the protocol
        """
        pass

    async def validate_message(self, message: Dict[str, Any]) -> bool:
        """
        Validate message structure (optional override).

        Args:
            message: Message to validate

        Returns:
            True if message is valid
        """
        return True

    async def initialize(self) -> None:
        """
        Initialize the protocol adapter (optional override).
        Called when the adapter is registered with the server.
        """
        pass

    async def shutdown(self) -> None:
        """
        Shutdown the protocol adapter (optional override).
        Called when the server is shutting down.
        """
        pass

    def create_error_response(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create protocol-specific error response (optional override).

        Args:
            error: The exception that occurred
            context: Additional context about the error

        Returns:
            Protocol-specific error message dictionary
        """
        return {
            "error": True,
            "message": str(error),
            "type": type(error).__name__,
            "context": context or {}
        }


class ProtocolNegotiator:
    """
    Handles protocol negotiation and adapter selection.
    """

    def __init__(self):
        self._adapters: Dict[ProtocolType, ProtocolAdapter] = {}

    def register_adapter(self, adapter: ProtocolAdapter) -> None:
        """Register a protocol adapter"""
        protocol_type = adapter.get_protocol_info().protocol_type
        self._adapters[protocol_type] = adapter

    def get_adapter(self, protocol_type: ProtocolType) -> Optional[ProtocolAdapter]:
        """Get adapter by protocol type"""
        return self._adapters.get(protocol_type)

    def detect_protocol(self, data: bytes) -> Optional[ProtocolType]:
        """
        Detect protocol from raw data.

        Args:
            data: Raw message bytes

        Returns:
            Detected protocol type or None
        """
        for adapter in self._adapters.values():
            if adapter.supports_protocol(data):
                return adapter.get_protocol_info().protocol_type
        return None

    def list_supported_protocols(self) -> Sequence[ProtocolInfo]:
        """List all supported protocols"""
        return [adapter.get_protocol_info() for adapter in self._adapters.values()]


def convert_protocol_type_to_wire(protocol_type: ProtocolType) -> "WireProtocol":
    """Convert a ``ProtocolType`` enum to the matching ``WireProtocol`` enum.

    Import is deferred to avoid a top-level ``common → server`` cycle.
    """
    from mars.common.wire import WireProtocol  # noqa: PLC0415
    mapping = {
        ProtocolType.AG_UI: WireProtocol.AG_UI,
        ProtocolType.A2A:   WireProtocol.A2A,
        ProtocolType.MCP:   WireProtocol.MCP,
        ProtocolType.MARS:  WireProtocol.MARS,
    }
    result = mapping.get(protocol_type)
    if result is None:
        raise ValueError(f"No WireProtocol mapping for {protocol_type!r}")
    return result


def convert_wire_to_protocol_type(wire_protocol: "WireProtocol") -> ProtocolType:
    """Convert a ``WireProtocol`` enum to the matching ``ProtocolType`` enum."""
    from mars.common.wire import WireProtocol  # noqa: PLC0415
    mapping = {
        WireProtocol.AG_UI: ProtocolType.AG_UI,
        WireProtocol.A2A:   ProtocolType.A2A,
        WireProtocol.MCP:   ProtocolType.MCP,
        WireProtocol.MARS:  ProtocolType.MARS,
    }
    result = mapping.get(wire_protocol)
    if result is None:
        raise ValueError(f"No ProtocolType mapping for {wire_protocol!r}")
    return result


def create_protocol_adapter(protocol_type: ProtocolType, server: Any) -> ProtocolAdapter:
    """
    Factory function to create protocol adapter instances.

    Args:
        protocol_type: Type of protocol adapter to create
        server: MARSServer instance

    Returns:
        Protocol adapter instance

    Raises:
        ValueError: If protocol type is not supported
    """
    # Import adapter implementations to avoid circular imports
    from .ag_ui import AGUIProtocolAdapter
    from .a2a import A2AProtocolAdapter
    from .mcp import MCPProtocolAdapter
    from .mars import MARSProtocolAdapter

    adapters = {
        ProtocolType.AG_UI: AGUIProtocolAdapter,
        ProtocolType.A2A: A2AProtocolAdapter,
        ProtocolType.MCP: MCPProtocolAdapter,
        ProtocolType.MARS: MARSProtocolAdapter,
    }

    adapter_class = adapters.get(protocol_type)
    if adapter_class is None:
        raise ValueError(f"Unsupported protocol type: {protocol_type}")

    return adapter_class(server)
