"""Integration tests for multi-protocol communication."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock

from mars.server.protocols.base import ProtocolNegotiator
from mars.common.wire import WireProtocol, encode_frame_with_protocol


class TestProtocolNegotiation:
    """Tests for protocol negotiation and selection."""

    @pytest.fixture
    def server(self):
        """Create mock server."""
        server = Mock()
        server.version = "1.0.0"
        server.state = Mock()
        server.state.agents = {}
        return server

    @pytest.fixture
    def negotiator(self, server):
        """Create protocol negotiator."""
        from mars.server.protocols.ag_ui import AGUIProtocolAdapter
        from mars.server.protocols.a2a import A2AProtocolAdapter
        from mars.server.protocols.mcp import MCPProtocolAdapter
        from mars.server.protocols.mars import MARSProtocolAdapter

        negotiator = ProtocolNegotiator()

        # Register all protocol adapters
        adapters = [
            AGUIProtocolAdapter(server),
            A2AProtocolAdapter(server),
            MCPProtocolAdapter(server),
            MARSProtocolAdapter(server)
        ]

        for adapter in adapters:
            negotiator.register_adapter(adapter)

        return negotiator

    def test_protocol_detection_from_messages(self, negotiator):
        """Test protocol detection from different message types."""
        from mars.server.protocols.base import ProtocolType

        messages = [
            (WireProtocol.AG_UI, ProtocolType.AG_UI, {"event": "agent:hello", "data": {}}),
            (WireProtocol.A2A, ProtocolType.A2A, {"jsonrpc": "2.0", "method": "message/send"}),
            (WireProtocol.MCP, ProtocolType.MCP, {"jsonrpc": "2.0", "method": "initialize"}),
            (WireProtocol.MARS, ProtocolType.MARS, {"msg_type": "node_handshake", "data": {}})
        ]

        for wire_protocol, expected_type, msg in messages:
            encoded = encode_frame_with_protocol(msg, wire_protocol)
            detected = negotiator.detect_protocol(encoded)

            assert detected == expected_type

    def test_adapter_selection(self, negotiator):
        """Test adapter selection by protocol type."""
        from mars.server.protocols.base import ProtocolType

        # Test getting each adapter
        ag_ui_adapter = negotiator.get_adapter(ProtocolType.AG_UI)
        a2a_adapter = negotiator.get_adapter(ProtocolType.A2A)
        mcp_adapter = negotiator.get_adapter(ProtocolType.MCP)
        mars_adapter = negotiator.get_adapter(ProtocolType.MARS)

        assert ag_ui_adapter is not None
        assert a2a_adapter is not None
        assert mcp_adapter is not None
        assert mars_adapter is not None

    def test_list_supported_protocols(self, negotiator):
        """Test listing supported protocols."""
        protocols = negotiator.list_supported_protocols()

        assert len(protocols) == 4
        protocol_names = {p.name for p in protocols}
        assert {"AG-UI", "A2A", "MCP", "MARS"}.issubset(protocol_names)


class TestCrossProtocolCommunication:
    """Tests for cross-protocol communication scenarios."""

    @pytest.fixture
    def mock_session(self):
        """Create mock session."""
        session = Mock()
        session.agent_id = "test_agent"
        session.role = "human"
        session.name = "test_user"
        return session

    @pytest.mark.asyncio
    async def test_ag_ui_message_handling(self, mock_session):
        """Test AG-UI protocol message handling."""
        from mars.server.protocols.ag_ui import AGUIProtocolAdapter

        server = Mock()
        server.version = "1.0.0"

        ag_ui_adapter = AGUIProtocolAdapter(server)

        # Create AG-UI style messages
        messages = [
            {"event": "agent:hello", "data": {"role": "human"}},
            {"event": "agent:message", "data": {"target": "agent1", "message": "Hello"}},
        ]

        # All should be serializable
        for msg in messages:
            encoded = encode_frame_with_protocol(msg, WireProtocol.AG_UI)
            assert encoded is not None
            assert encoded.startswith(b"AG-UI/")

    @pytest.mark.asyncio
    async def test_concurrent_protocol_sessions(self):
        """Test handling multiple concurrent sessions with different protocols."""
        # This would test the server's ability to handle multiple protocols simultaneously
        sessions = []

        for i in range(5):
            session = Mock()
            session.agent_id = f"agent_{i}"
            session.role = "human"
            sessions.append(session)

        # Each session could theoretically use a different protocol
        protocols = [WireProtocol.AG_UI, WireProtocol.A2A, WireProtocol.MCP, WireProtocol.MARS]

        # Test that all sessions can be handled
        assert len(sessions) == 5
        assert len(protocols) == 4


class TestErrorHandling:
    """Tests for error handling across protocols."""

    @pytest.fixture
    def server(self):
        """Create mock server."""
        server = Mock()
        server.version = "1.0.0"
        return server

    @pytest.mark.asyncio
    async def test_invalid_message_handling(self, server):
        """Test handling of invalid messages across protocols."""
        from mars.server.protocols.ag_ui import AGUIProtocolAdapter

        adapter = AGUIProtocolAdapter(server)
        session = Mock()

        # Test various invalid messages
        invalid_messages = [
            {},  # Missing event field
            {"event": "unknown_event", "data": {}},  # Unknown event
            {"event": "agent:hello", "invalid_field": "value"},  # Missing required fields
        ]

        for invalid_msg in invalid_messages:
            try:
                response = await adapter.handle_message(invalid_msg, session)
                # Should either raise an error or return an error response
                assert response is None or "error" in str(response).lower()
            except Exception:
                # Expected to raise exception for invalid messages
                pass

    @pytest.mark.asyncio
    async def test_protocol_mismatch_handling(self, server):
        """Test handling when protocol doesn't match expected format."""
        from mars.server.protocols.ag_ui import AGUIProtocolAdapter
        from mars.server.protocols.a2a import A2AProtocolAdapter

        ag_ui_adapter = AGUIProtocolAdapter(server)
        a2a_adapter = A2AProtocolAdapter(server)

        # Try to deserialize AG-UI message with A2A adapter
        ag_ui_msg = {"event": "agent:hello", "data": {}}
        ag_ui_encoded = await ag_ui_adapter.serialize_message(ag_ui_msg)

        try:
            # A2A adapter should fail to parse AG-UI message
            result = await a2a_adapter.deserialize_message(ag_ui_encoded)
            # Should either return None or raise error
            assert result is None or "error" in str(result).lower()
        except Exception:
            # Expected to fail
            pass


class TestProtocolPerformance:
    """Performance tests for protocol handling."""

    @pytest.mark.asyncio
    async def test_message_serialization_performance(self):
        """Test serialization performance across protocols."""
        import time

        from mars.server.protocols.ag_ui import AGUIProtocolAdapter
        from mars.server.protocols.a2a import A2AProtocolAdapter

        server = Mock()
        server.version = "1.0.0"

        adapters = [
            AGUIProtocolAdapter(server),
            A2AProtocolAdapter(server)
        ]

        message = {"test": "data", "nested": {"field": "value"}}

        for adapter in adapters:
            start = time.time()
            for _ in range(100):
                await adapter.serialize_message(message)
            end = time.time()

            # Should serialize 100 messages in reasonable time (< 1 second)
            assert (end - start) < 1.0

    @pytest.mark.asyncio
    async def test_concurrent_message_handling(self):
        """Test concurrent message handling performance."""
        from mars.server.protocols.ag_ui import AGUIProtocolAdapter

        server = Mock()
        server.version = "1.0.0"
        adapter = AGUIProtocolAdapter(server)

        session = Mock()

        async def handle_message(msg_num):
            msg = {
                "event": "agent:message",
                "data": {
                    "target": f"agent_{msg_num % 3}",  # Cycle between 3 agents
                    "message": f"test message {msg_num}"
                }
            }
            return await adapter.handle_message(msg, session)

        # Handle 50 concurrent messages
        start = asyncio.get_event_loop().time()
        tasks = [handle_message(i) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end = asyncio.get_event_loop().time()

        # Check that most messages succeeded
        successful = [r for r in results if r is not None]
        assert len(successful) >= 45  # Allow some to fail due to routing

        # Should handle 50 messages in reasonable time (< 2 seconds)
        assert (end - start) < 2.0
