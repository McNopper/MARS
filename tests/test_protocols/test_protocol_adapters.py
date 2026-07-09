"""Tests for protocol adapters."""

import asyncio
import pytest
from unittest.mock import Mock, MagicMock

from mars.server.protocols.base import ProtocolAdapter, ProtocolInfo, ProtocolType
from mars.server.protocols.ag_ui import AGUIProtocolAdapter
from mars.server.protocols.a2a import A2AProtocolAdapter
from mars.server.protocols.mcp import MCPProtocolAdapter
from mars.server.protocols.mars import MARSProtocolAdapter


class MockTaskManager:
    """Mock task manager for testing."""
    async def create_task(self, task_id, message):
        """Mock create task."""
        return Mock(status="submitted", created_at=Mock(__isoformat__=lambda: "2024-01-01T00:00:00"))

    async def get_task(self, task_id):
        """Mock get task."""
        return Mock(status="completed", result="test result", updated_at=Mock(__isoformat__=lambda: "2024-01-01T00:01:00"), error=None)

    async def cancel_task(self, task_id):
        """Mock cancel task."""
        return Mock(status="canceled", updated_at=Mock(__isoformat__=lambda: "2024-01-01T00:02:00"))

    async def create_task_stream(self, task_id, session):
        """Mock create task stream."""
        return f"/stream/{task_id}"

    async def resubscribe_stream(self, task_id, stream_id, session):
        """Mock resubscribe stream."""
        return f"/stream/{task_id}"


class MockAgentCardManager:
    """Mock agent card manager for testing."""
    async def get_agent_card(self, agent_id):
        """Mock get agent card."""
        return {"agent_id": agent_id, "name": "Test Agent"}


class MockToolRegistry:
    """Mock tool registry for testing."""
    async def list_tools(self, session):
        """Mock list tools."""
        return [{"name": "test_tool", "description": "Test tool", "inputSchema": {}}]

    async def call_tool(self, tool_name, arguments, session):
        """Mock call tool."""
        return {"result": f"Called {tool_name}"}

    async def register_service_tools(self, service_id, tools):
        """Mock register tools."""
        pass

    async def unregister_service_tools(self, service_id):
        """Mock unregister tools."""
        pass


class MockResourceRegistry:
    """Mock resource registry for testing."""
    async def list_resources(self, session):
        """Mock list resources."""
        return [{"uri": "test://resource", "name": "Test Resource"}]

    async def read_resource(self, uri, session):
        """Mock read resource."""
        return {"type": "text", "text": "Test content"}


class MockPromptRegistry:
    """Mock prompt registry for testing."""
    async def list_prompts(self, session):
        """Mock list prompts."""
        return [{"name": "test_prompt", "description": "Test prompt"}]

    async def get_prompt(self, prompt_name, arguments, session):
        """Mock get prompt."""
        return {"role": "user", "content": "Test prompt"}


class MockNodeRegistry:
    """Mock node registry for testing."""
    async def register_node(self, node_id, version, capabilities, session):
        """Mock register node."""
        pass

    async def update_last_seen(self, node_id):
        """Mock update last seen."""
        pass


class MockSecurityManager:
    """Mock security manager for testing."""
    pass


class MockServer:
    """Mock server for testing."""
    def __init__(self):
        self.version = "1.0.0"
        self.node_id = "test-node"
        self.state = Mock()
        self.state.agents = {}
        self._messages = []
        self._artifacts = {}
        self._errors = []
        self._task_manager = MockTaskManager()
        self._agent_card_manager = MockAgentCardManager()
        self._tool_registry = MockToolRegistry()
        self._resource_registry = MockResourceRegistry()
        self._prompt_registry = MockPromptRegistry()
        self._node_registry = MockNodeRegistry()
        self._security_manager = MockSecurityManager()

    async def route_message_to_agent(self, target, message, session):
        """Mock route message to agent."""
        self._messages.append({"target": target, "message": message})
        return f"Routed to {target}: {message}"

    async def broadcast_state_update(self, data):
        """Mock broadcast state update."""
        self._messages.append({"type": "state_update", "data": data})

    async def call_tool(self, tool_name, tool_args):
        """Mock tool call."""
        return {"tool": tool_name, "result": f"Called {tool_name}"}

    async def store_artifact(self, artifact_id, artifact_data):
        """Mock store artifact."""
        self._artifacts[artifact_id] = artifact_data

    async def handle_error(self, error):
        """Mock handle error."""
        self._errors.append(error)

    async def route_a2a_message(self, target_agent, message, task_id):
        """Mock route A2A message."""
        self._messages.append({"target": target_agent, "message": message, "task_id": task_id})

    async def create_virtual_agent(self, agent_id, node_id, agent_info):
        """Mock create virtual agent."""
        self.state.agents[agent_id] = Mock(id=agent_id, name=agent_id)

    async def remove_virtual_agent(self, agent_id):
        """Mock remove virtual agent."""
        if agent_id in self.state.agents:
            del self.state.agents[agent_id]

    async def route_federated_message(self, source_agent, target_agent, payload, timestamp):
        """Mock route federated message."""
        self._messages.append({"source": source_agent, "target": target_agent, "payload": payload})
        return {"status": "delivered"}

    async def deliver_federated_response(self, source_agent, target_agent, payload):
        """Mock deliver federated response."""
        self._messages.append({"source": source_agent, "target": target_agent, "payload": payload})

    async def store_federated_artifact(self, artifact_id, source_node, content, tags):
        """Mock store federated artifact."""
        self._artifacts[artifact_id] = {"source": source_node, "content": content, "tags": tags}

    async def broadcast_to_federation(self, announcement):
        """Mock broadcast to federation."""
        self._messages.append({"type": "federation_broadcast", "data": announcement})


class MockSession:
    """Mock session for testing."""
    def __init__(self):
        self.agent_id = "test_agent"
        self.role = "human"
        self.name = "test_user"


class TestProtocolAdapterBase:
    """Tests for base protocol adapter interface."""

    def test_protocol_adapter_abstract_methods(self):
        """Test that protocol adapter requires abstract methods."""
        # This should fail to instantiate due to abstract methods
        with pytest.raises(TypeError):
            ProtocolAdapter(MockServer())

    def test_protocol_info_structure(self):
        """Test protocol info data structure."""
        protocol_info = ProtocolInfo(
            name="TestProtocol",
            version="1.0.0",
            protocol_type=ProtocolType.AG_UI,  # Use a valid protocol type
            capabilities=["test_capability"],
            description="Test protocol"
        )

        assert protocol_info.name == "TestProtocol"
        assert protocol_info.version == "1.0.0"
        assert protocol_info.protocol_type == ProtocolType.AG_UI
        assert len(protocol_info.capabilities) == 1
        assert protocol_info.description == "Test protocol"


class TestAGUIProtocolAdapter:
    """Tests for AG-UI protocol adapter."""

    def test_ag_ui_adapter_initialization(self):
        """Test AG-UI adapter initialization."""
        server = MockServer()
        adapter = AGUIProtocolAdapter(server)

        assert adapter.get_protocol_info().name == "AG-UI"
        assert adapter.get_protocol_info().protocol_type == ProtocolType.AG_UI

    def test_ag_ui_supports_own_protocol(self):
        """Test AG-UI adapter supports AG-UI magic header."""
        adapter = AGUIProtocolAdapter(MockServer())
        magic_header = b"AG-UI/0.1.0"

        assert adapter.supports_protocol(magic_header) is True

    @pytest.mark.asyncio
    async def test_ag_ui_message_serialization(self):
        """Test AG-UI message serialization."""
        adapter = AGUIProtocolAdapter(MockServer())
        message = {"event": "agent:hello", "data": {"role": "human"}}

        serialized = await adapter.serialize_message(message)

        assert serialized.startswith(b"AG-UI/")
        assert b"agent:hello" in serialized

    @pytest.mark.asyncio
    async def test_ag_ui_message_deserialization(self):
        """Test AG-UI message deserialization."""
        adapter = AGUIProtocolAdapter(MockServer())
        message = {"event": "agent:hello", "data": {"role": "human"}}

        serialized = await adapter.serialize_message(message)
        deserialized = await adapter.deserialize_message(serialized)

        assert deserialized["event"] == "agent:hello"
        assert deserialized["data"]["role"] == "human"

    @pytest.mark.asyncio
    async def test_ag_ui_hello_event_handling(self):
        """Test AG-UI hello event handling."""
        server = MockServer()
        adapter = AGUIProtocolAdapter(server)
        session = MockSession()

        hello_event = {"event": "agent:hello", "data": {"role": "human"}}
        response = await adapter.handle_message(hello_event, session)

        assert response["event"] == "agent:welcome"
        assert "server_version" in response["data"]

    @pytest.mark.asyncio
    async def test_ag_ui_message_event_handling(self):
        """Test AG-UI message event handling."""
        server = MockServer()
        adapter = AGUIProtocolAdapter(server)
        session = MockSession()

        message_event = {
            "event": "agent:message",
            "data": {"target": "agent1", "message": "Hello"}
        }

        response = await adapter.handle_message(message_event, session)

        # Response should be None for message events (async routing)
        assert response is None or response.get("event") == "agent:message"


class TestA2AProtocolAdapter:
    """Tests for A2A protocol adapter."""

    def test_a2a_adapter_initialization(self):
        """Test A2A adapter initialization."""
        server = MockServer()
        adapter = A2AProtocolAdapter(server)

        assert adapter.get_protocol_info().name == "A2A"
        assert adapter.get_protocol_info().protocol_type == ProtocolType.A2A

    def test_a2a_supports_own_protocol(self):
        """Test A2A adapter supports A2A magic header."""
        adapter = A2AProtocolAdapter(MockServer())
        magic_header = b"A2A-JSONRPC/0.3.0"

        assert adapter.supports_protocol(magic_header) is True

    def test_a2a_jsonrpc_structure(self):
        """Test A2A JSON-RPC message structure."""
        adapter = A2AProtocolAdapter(MockServer())
        request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "test"}]}},
            "id": 1
        }

        serialized = await_adapter_serialize(adapter, request)
        deserialized = await_adapter_deserialize(adapter, serialized)

        assert deserialized["jsonrpc"] == "2.0"
        assert deserialized["method"] == "message/send"

    def test_a2a_message_send_handling(self):
        """Test A2A message/send method handling."""
        server = MockServer()
        adapter = A2AProtocolAdapter(server)
        session = MockSession()

        request = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello"}]
                }
            },
            "id": 1
        }

        response = await_adapter_handle(adapter, request, session)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response


class TestMCPProtocolAdapter:
    """Tests for MCP protocol adapter."""

    def test_mcp_adapter_initialization(self):
        """Test MCP adapter initialization."""
        server = MockServer()
        adapter = MCPProtocolAdapter(server)

        assert adapter.get_protocol_info().name == "MCP"
        assert adapter.get_protocol_info().protocol_type == ProtocolType.MCP

    def test_mcp_supports_own_protocol(self):
        """Test MCP adapter supports MCP magic header."""
        adapter = MCPProtocolAdapter(MockServer())
        magic_header = b"MCP-STDIO/2024-11-05"

        assert adapter.supports_protocol(magic_header) is True

    def test_mcp_initialize_handling(self):
        """Test MCP initialize method handling."""
        server = MockServer()
        adapter = MCPProtocolAdapter(server)
        session = MockSession()

        request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0.0"}
            },
            "id": 1
        }

        response = await_adapter_handle(adapter, request, session)

        assert response["jsonrpc"] == "2.0"
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2024-11-05"


class TestMARSProtocolAdapter:
    """Tests for MARS federation protocol adapter."""

    def test_mars_adapter_initialization(self):
        """Test MARS adapter initialization."""
        server = MockServer()
        adapter = MARSProtocolAdapter(server)

        assert adapter.get_protocol_info().name == "MARS"
        assert adapter.get_protocol_info().protocol_type == ProtocolType.MARS

    def test_mars_supports_own_protocol(self):
        """Test MARS adapter supports MARS magic header."""
        adapter = MARSProtocolAdapter(MockServer())
        magic_header = b"MARS-FED/1.0.0"

        assert adapter.supports_protocol(magic_header) is True

    def test_mars_node_handshake_structure(self):
        """Test MARS node handshake message structure."""
        server = MockServer()
        adapter = MARSProtocolAdapter(server)

        handshake = {
            "msg_type": "node_handshake",
            "data": {
                "node_id": "test_node",
                "version": "1.0.0",
                "agents": [],
                "capabilities": []
            }
        }

        serialized = await_adapter_serialize(adapter, handshake)
        deserialized = await_adapter_deserialize(adapter, serialized)

        assert deserialized["msg_type"] == "node_handshake"
        assert deserialized["data"]["node_id"] == "test_node"


# Helper functions for async testing

def await_adapter_serialize(adapter, message):
    """Helper to call adapter serialize method."""
    return asyncio.run(adapter.serialize_message(message))


def await_adapter_deserialize(adapter, data):
    """Helper to call adapter deserialize method."""
    return asyncio.run(adapter.deserialize_message(data))


def await_adapter_handle(adapter, message, session):
    """Helper to call adapter handle method."""
    return asyncio.run(adapter.handle_message(message, session))
