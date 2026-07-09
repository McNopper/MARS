"""AG-UI Client for MARS - Human CLI to agent server communication using AG-UI protocol.

This client implements the AG-UI protocol for human-agent interaction,
replacing the legacy JSON-line protocol with standardized AG-UI events.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, Optional

from mars.common.wire import WireProtocol, encode_frame_with_protocol


class AGUIClient:
    """AG-UI Protocol Client for MARS CLI.

    Implements AG-UI protocol events:
    - agent:hello - Initial connection handshake
    - agent:message - Bi-directional messaging
    - agent:state_update - State synchronization
    - agent:tool_call - Tool invocation
    - agent:stream_start - Begin streaming response
    - agent:stream_chunk - Streaming content
    - agent:stream_end - End streaming
    - agent:artifact - Artifact generation
    - agent:error - Error reporting
    """

    AG_UI_PROTOCOL_VERSION = "0.1.0"

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Initialize AG-UI client.

        Args:
            reader: Stream reader for receiving messages
            writer: Stream writer for sending messages
        """
        self._reader = reader
        self._writer = writer
        self._connected = False
        self._agent_roster: Dict[str, Dict[str, Any]] = {}
        self._server_capabilities: List[str] = []

    async def connect(self, client_name: str = "cli-user") -> Dict[str, Any]:
        """
        Connect to server using AG-UI protocol.

        Args:
            client_name: Client identifier

        Returns:
            Welcome message from server
        """
        # Send agent:hello event
        hello_event = self._build_hello_event(client_name)
        await self._send_event(hello_event)

        # Wait for agent:welcome response
        welcome_data = await self._receive_event("agent:welcome")
        self._connected = True

        # Update agent roster and capabilities
        if welcome_data:
            self._agent_roster = welcome_data.get("agents", {})
            self._server_capabilities = welcome_data.get("capabilities", [])

        return welcome_data

    async def send_message(self, target: str, message: str) -> None:
        """
        Send message to target agent.

        Args:
            target: Target agent ID
            message: Message content
        """
        message_event = self._build_message_event(target, message)
        await self._send_event(message_event)

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call tool on service agent.

        Args:
            tool_name: Tool identifier
            arguments: Tool arguments

        Returns:
            Tool result
        """
        tool_call_event = self._build_tool_call_event(tool_name, arguments)
        await self._send_event(tool_call_event)

        # Wait for tool result
        result_data = await self._receive_event("agent:tool_result")
        return result_data

    async def request_state_update(self) -> Dict[str, Any]:
        """
        Request state synchronization.

        Returns:
            Current server state
        """
        state_update_event = {
            "event": "agent:state_update",
            "data": {}
        }
        await self._send_event(state_update_event)

        # Wait for state update
        state_data = await self._receive_event("agent:state_update")
        return state_data

    def _build_hello_event(self, client_name: str) -> Dict[str, Any]:
        """Build agent:hello event."""
        return {
            "event": "agent:hello",
            "data": {
                "client_name": client_name,
                "role": "human",
                "protocol_version": self.AG_UI_PROTOCOL_VERSION,
                "capabilities": [
                    "send_message",
                    "receive_messages",
                    "call_tools",
                    "receive_artifacts",
                    "state_updates"
                ]
            }
        }

    def _build_message_event(self, target: str, message: str) -> Dict[str, Any]:
        """Build agent:message event."""
        return {
            "event": "agent:message",
            "data": {
                "target": target,
                "message": message
            }
        }

    def _build_tool_call_event(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Build agent:tool_call event."""
        return {
            "event": "agent:tool_call",
            "data": {
                "tool": tool_name,
                "args": arguments
            }
        }

    async def _send_event(self, event: Dict[str, Any]) -> None:
        """
        Send AG-UI event to server.

        Args:
            event: AG-UI event dictionary
        """
        try:
            # Use AG-UI protocol framing
            frame_data = encode_frame_with_protocol(
                event,
                WireProtocol.AG_UI,
                protocol_version=self.AG_UI_PROTOCOL_VERSION
            )
            self._writer.write(frame_data)
            await self._writer.drain()
        except Exception as e:
            raise ConnectionError(f"Failed to send AG-UI event: {e}")

    async def _receive_event(self, expected_event_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Receive AG-UI event from server.

        Args:
            expected_event_type: Optional event type to wait for

        Returns:
            Received event data
        """
        while not self._reader.at_eof():
            try:
                raw = await self._reader.readline()
                if not raw:
                    continue

                # Parse AG-UI protocol frame
                from mars.common.wire import decode_frame_with_protocol
                protocol_msg = decode_frame_with_protocol(raw)

                if not protocol_msg:
                    continue

                protocol, message = protocol_msg

                # Verify it's AG-UI protocol
                if protocol != WireProtocol.AG_UI:
                    continue

                event_type = message.get("event")
                event_data = message.get("data", {})

                # Return if this is the expected event type
                if expected_event_type is None or event_type == expected_event_type:
                    return event_data

            except Exception as e:
                print(f"Error receiving AG-UI event: {e}", file=sys.stderr)
                continue

        return {}

    async def receive_message_loop(self, message_handler: callable) -> None:
        """
        Continuous loop for receiving AG-UI events.

        Args:
            message_handler: Callback function for handling received events
        """
        while not self._reader.at_eof():
            try:
                raw = await self._reader.readline()
                if not raw:
                    continue

                # Parse AG-UI protocol frame
                from mars.common.wire import decode_frame_with_protocol
                protocol_msg = decode_frame_with_protocol(raw)

                if not protocol_msg:
                    continue

                protocol, message = protocol_msg

                # Verify it's AG-UI protocol
                if protocol != WireProtocol.AG_UI:
                    continue

                event_type = message.get("event")
                event_data = message.get("data", {})

                # Handle event based on type
                if event_type == "agent:message":
                    await message_handler("message", event_data)
                elif event_type == "agent:artifact":
                    await message_handler("artifact", event_data)
                elif event_type == "agent:error":
                    await message_handler("error", event_data)
                elif event_type == "agent:state_update":
                    await message_handler("state_update", event_data)
                elif event_type == "agent:stream_start":
                    await message_handler("stream_start", event_data)
                elif event_type == "agent:stream_chunk":
                    await message_handler("stream_chunk", event_data)
                elif event_type == "agent:stream_end":
                    await message_handler("stream_end", event_data)

            except Exception as e:
                print(f"Error in receive loop: {e}", file=sys.stderr)
                continue

    async def close(self) -> None:
        """Close the AG-UI connection."""
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except Exception:
            pass

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected

    @property
    def agent_roster(self) -> Dict[str, Dict[str, Any]]:
        """Get current agent roster."""
        return self._agent_roster

    @property
    def server_capabilities(self) -> List[str]:
        """Get server capabilities."""
        return self._server_capabilities
