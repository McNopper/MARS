"""Tests for multi-protocol wire framing."""

import pytest

from mars.common.wire import (
    WireProtocol,
    encode_frame,
    decode_frame,
    encode_frame_with_protocol,
    decode_frame_with_protocol,
    detect_protocol_from_data,
)
from mars.server.protocols.base import (
    ProtocolType,
    convert_protocol_type_to_wire,
    convert_wire_to_protocol_type,
)


class TestWireProtocol:
    """Tests for wire protocol detection and framing."""

    @pytest.mark.asyncio
    async def test_ag_ui_protocol_detection(self):
        """Test that AG-UI protocol is detected from magic header."""
        from mars.server.protocols.ag_ui import AGUIProtocolAdapter
        adapter = AGUIProtocolAdapter(None)

        message = {"event": "agent:hello", "data": {"role": "human"}}
        encoded = await adapter.serialize_message(message)

        protocol = detect_protocol_from_data(encoded)
        assert protocol == WireProtocol.AG_UI

    @pytest.mark.asyncio
    async def test_a2a_protocol_detection(self):
        """Test that A2A protocol is detected from magic header."""
        from mars.server.protocols.a2a import A2AProtocolAdapter
        adapter = A2AProtocolAdapter(None)

        message = {"jsonrpc": "2.0", "method": "message/send", "id": 1}
        encoded = await adapter.serialize_message(message)

        protocol = detect_protocol_from_data(encoded)
        assert protocol == WireProtocol.A2A

    @pytest.mark.asyncio
    async def test_mcp_protocol_detection(self):
        """Test that MCP protocol is detected from magic header."""
        from mars.server.protocols.mcp import MCPProtocolAdapter
        adapter = MCPProtocolAdapter(None)

        message = {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        encoded = await adapter.serialize_message(message)

        protocol = detect_protocol_from_data(encoded)
        assert protocol == WireProtocol.MCP

    @pytest.mark.asyncio
    async def test_mars_protocol_detection(self):
        """Test that MARS protocol is detected from magic header."""
        from mars.server.protocols.mars import MARSProtocolAdapter
        adapter = MARSProtocolAdapter(None)

        message = {"msg_type": "node_handshake", "data": {}}
        encoded = await adapter.serialize_message(message)

        protocol = detect_protocol_from_data(encoded)
        assert protocol == WireProtocol.MARS

    def test_protocol_encode_decode_roundtrip(self):
        """Test protocol-specific encode/decode roundtrip."""
        original = {"event": "agent:hello", "data": {"role": "human"}}

        # Test AG-UI protocol
        encoded = encode_frame_with_protocol(original, WireProtocol.AG_UI)
        protocol, decoded = decode_frame_with_protocol(encoded)

        assert protocol == WireProtocol.AG_UI
        assert decoded == original

    def test_protocol_type_conversion(self):
        """Test protocol type to wire protocol conversion."""
        # Test ProtocolType to WireProtocol conversion
        assert convert_protocol_type_to_wire(ProtocolType.AG_UI) == WireProtocol.AG_UI
        assert convert_protocol_type_to_wire(ProtocolType.A2A) == WireProtocol.A2A
        assert convert_protocol_type_to_wire(ProtocolType.MCP) == WireProtocol.MCP
        assert convert_protocol_type_to_wire(ProtocolType.MARS) == WireProtocol.MARS

        # Test WireProtocol to ProtocolType conversion
        assert convert_wire_to_protocol_type(WireProtocol.AG_UI) == ProtocolType.AG_UI
        assert convert_wire_to_protocol_type(WireProtocol.A2A) == ProtocolType.A2A
        assert convert_wire_to_protocol_type(WireProtocol.MCP) == ProtocolType.MCP
        assert convert_wire_to_protocol_type(WireProtocol.MARS) == ProtocolType.MARS

    def test_invalid_protocol_detection_raises_error(self):
        """Test that invalid protocol detection raises ValueError."""
        invalid_data = b"invalid protocol data"

        with pytest.raises(ValueError, match="Unknown protocol"):
            detect_protocol_from_data(invalid_data)

    def test_empty_data_detection_raises_error(self):
        """Test that empty data detection raises ValueError."""
        with pytest.raises(ValueError, match="Cannot detect protocol from empty data"):
            detect_protocol_from_data(b"")


class TestMultiProtocolMessageHandling:
    """Tests for multi-protocol message handling."""

    def test_different_protocols_coexist(self):
        """Test that messages from different protocols can coexist."""
        messages = [
            (WireProtocol.AG_UI, {"event": "agent:hello", "data": {}}),
            (WireProtocol.A2A, {"jsonrpc": "2.0", "method": "message/send"}),
            (WireProtocol.MCP, {"jsonrpc": "2.0", "method": "initialize"}),
            (WireProtocol.MARS, {"msg_type": "node_handshake", "data": {}})
        ]

        for protocol, msg in messages:
            encoded = encode_frame_with_protocol(msg, protocol)
            detected_protocol = detect_protocol_from_data(encoded)

            assert detected_protocol == protocol

    def test_protocol_specific_serialization(self):
        """Test that each protocol serializes correctly."""
        test_cases = [
            (WireProtocol.AG_UI, {"event": "agent:message", "data": {"message": "hello"}}),
            (WireProtocol.A2A, {"jsonrpc": "2.0", "method": "message/send"}),
        ]

        for protocol, msg in test_cases:
            encoded = encode_frame_with_protocol(msg, protocol)
            decoded_protocol, decoded_msg = decode_frame_with_protocol(encoded)

            assert decoded_protocol == protocol
            assert decoded_msg == msg

    def test_invalid_protocol_raises_error(self):
        """Test that invalid protocol selection raises ValueError."""
        message = {"test": "data"}

        with pytest.raises(ValueError, match="Unsupported protocol"):
            encode_frame_with_protocol(message, "invalid_protocol")  # type: ignore
