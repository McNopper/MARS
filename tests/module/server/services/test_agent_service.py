"""Tests for the Agent Communication Service."""


import pytest

from mars.server.services.builtin.agent_service import AgentCommunicationService
from mars.server.services.registry import get_service


@pytest.fixture
def agent_service():
    """Create an agent communication service instance."""
    service = AgentCommunicationService()
    return service


@pytest.mark.asyncio
async def test_agent_service_initialization(agent_service):
    """Test that the agent service can be initialized."""
    assert agent_service.service_id == "agent-comm"
    assert agent_service.display_name == "Agent Communication Service"
    assert not agent_service.is_running

    await agent_service.initialize()
    assert agent_service.is_running

    await agent_service.shutdown()
    assert not agent_service.is_running


@pytest.mark.asyncio
async def test_agent_service_capabilities(agent_service):
    """Test that the agent service exposes the correct capabilities."""
    capabilities = agent_service.capabilities
    capability_names = [cap.name for cap in capabilities]

    assert "send_agent_message" in capability_names
    assert "list_available_agents" in capability_names
    assert "get_agent_info" in capability_names
    assert "broadcast_to_agents" in capability_names


@pytest.mark.asyncio
async def test_send_agent_message(agent_service):
    """Test sending a message to another agent."""
    await agent_service.initialize()

    result = await agent_service.call_tool(
        "send_agent_message",
        target_agent_id="agent.test@1",
        message="Hello, agent!",
        message_type="request"
    )

    assert result["success"] is True
    assert result["target_agent"] == "agent.test@1"
    assert result["status"] == "queued"
    assert "message_id" in result
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_list_available_agents(agent_service):
    """Test listing available agents."""
    await agent_service.initialize()

    result = await agent_service.call_tool(
        "list_available_agents",
        agent_type="all",
        include_details=False
    )

    assert "total" in result
    assert "agents" in result
    assert result["filter_type"] == "all"
    assert isinstance(result["agents"], list)


@pytest.mark.asyncio
async def test_get_agent_info(agent_service):
    """Test getting information about a specific agent."""
    await agent_service.initialize()

    result = await agent_service.call_tool(
        "get_agent_info",
        agent_id="agent.test@1"
    )

    assert result["agent_id"] == "agent.test@1"
    assert result["found"] is True
    assert "info" in result


@pytest.mark.asyncio
async def test_broadcast_to_agents(agent_service):
    """Test broadcasting a message to multiple agents."""
    await agent_service.initialize()

    result = await agent_service.call_tool(
        "broadcast_to_agents",
        message="Broadcast message",
        agent_type="LLMAgent",
        exclude_sender=True
    )

    assert result["success"] is True
    assert result["target_type"] == "LLMAgent"
    assert result["exclude_sender"] is True
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_get_pending_messages(agent_service):
    """Test retrieving pending messages from the queue."""
    await agent_service.initialize()

    # Send some messages
    await agent_service.call_tool(
        "send_agent_message",
        target_agent_id="agent1@1",
        message="Message 1"
    )
    await agent_service.call_tool(
        "send_agent_message",
        target_agent_id="agent2@1",
        message="Message 2"
    )

    # Get pending messages
    messages = await agent_service.get_pending_messages()
    assert len(messages) == 2
    assert messages[0]["to_agent"] == "agent1@1"
    assert messages[1]["to_agent"] == "agent2@1"


@pytest.mark.asyncio
async def test_message_handler_registration(agent_service):
    """Test registering and unregistering message handlers."""
    await agent_service.initialize()

    # Create a dummy handler
    async def dummy_handler(message):
        return {"handled": True}

    # Register handler
    agent_service.register_message_handler("test_handler", dummy_handler)
    assert "test_handler" in agent_service._message_handlers

    # Unregister handler
    agent_service.unregister_message_handler("test_handler")
    assert "test_handler" not in agent_service._message_handlers


def test_agent_service_from_registry():
    """Test that the agent service can be obtained from the registry."""
    service = get_service("agent-comm")
    assert isinstance(service, AgentCommunicationService)
    assert service.service_id == "agent-comm"


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_message(agent_service):
    """Test that calling an unknown tool returns an error message."""
    result = await agent_service.call_tool("unknown_tool")
    assert "Unknown agent communication tool" in str(result)
