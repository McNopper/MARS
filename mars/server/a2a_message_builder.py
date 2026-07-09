"""
A2A Message Builder

Constructs A2A protocol messages for agent-to-agent communication.
Provides type-safe message creation for all A2A methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4


@dataclass
class TextPart:
    """Text content part in A2A messages"""
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "text", "text": self.text}


@dataclass
class FilePart:
    """File content part in A2A messages"""
    filename: str
    content: bytes
    mime_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": "file",
            "filename": self.filename,
            "content": self.content,
            "mimeType": self.mime_type
        }


@dataclass
class DataPart:
    """Structured data part in A2A messages"""
    json_data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": "data", "data": self.json_data}


class A2AMessageBuilder:
    """
    Builder for constructing A2A protocol messages.

    Supports all A2A methods:
    - message/send
    - tasks/get
    - tasks/cancel
    - message/stream
    - tasks/resubscribe
    """

    def __init__(self):
        self._jsonrpc_version = "2.0"

    def create_request_id(self) -> str:
        """Generate unique request ID"""
        return str(uuid4())

    # message/send

    def build_message_send(
        self,
        message: Dict[str, Any],
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build message/send request.

        Args:
            message: A2A message structure
            request_id: Optional request ID (auto-generated if not provided)

        Returns:
            JSON-RPC request dictionary
        """
        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id or self.create_request_id(),
            "method": "message/send",
            "params": {"message": message}
        }

    def build_user_message(
        self,
        text: str,
        parts: Optional[List[Dict[str, Any]]] = None,
        target: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build user message structure.

        Args:
            text: Message text
            parts: Additional message parts (files, data)
            target: Target agent ID

        Returns:
            A2A message structure
        """
        message_parts = parts or []
        if text:
            message_parts.append({"kind": "text", "text": text})

        message = {
            "role": "user",
            "parts": message_parts
        }

        if target:
            message["target"] = target

        return message

    def build_agent_message(
        self,
        text: str,
        parts: Optional[List[Dict[str, Any]]] = None,
        source: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build agent message structure.

        Args:
            text: Message text
            parts: Additional message parts (files, data)
            source: Source agent ID

        Returns:
            A2A message structure
        """
        message_parts = parts or []
        if text:
            message_parts.append({"kind": "text", "text": text})

        message = {
            "role": "agent",
            "parts": message_parts
        }

        if source:
            message["source"] = source

        return message

    # tasks/get

    def build_tasks_get(
        self,
        task_id: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build tasks/get request.

        Args:
            task_id: Task identifier
            request_id: Optional request ID

        Returns:
            JSON-RPC request dictionary
        """
        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id or self.create_request_id(),
            "method": "tasks/get",
            "params": {"task_id": task_id}
        }

    def build_tasks_get_response(
        self,
        task_id: str,
        status: str,
        result: Optional[Any] = None,
        error: Optional[Dict[str, Any]] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build tasks/get response.

        Args:
            task_id: Task identifier
            status: Task status
            result: Task result
            error: Task error
            created_at: Task creation timestamp
            updated_at: Task update timestamp
            request_id: Request ID from original request

        Returns:
            JSON-RPC response dictionary
        """
        response_data = {
            "task_id": task_id,
            "status": status
        }

        if result is not None:
            response_data["result"] = result

        if error is not None:
            response_data["error"] = error

        if created_at:
            response_data["created_at"] = created_at

        if updated_at:
            response_data["updated_at"] = updated_at

        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id,
            "result": response_data
        }

    # tasks/cancel

    def build_tasks_cancel(
        self,
        task_id: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build tasks/cancel request.

        Args:
            task_id: Task identifier
            request_id: Optional request ID

        Returns:
            JSON-RPC request dictionary
        """
        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id or self.create_request_id(),
            "method": "tasks/cancel",
            "params": {"task_id": task_id}
        }

    # message/stream

    def build_message_stream(
        self,
        task_id: str,
        resubscribe: bool = False,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build message/stream request.

        Args:
            task_id: Task identifier
            resubscribe: Whether to resubscribe to existing stream
            request_id: Optional request ID

        Returns:
            JSON-RPC request dictionary
        """
        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id or self.create_request_id(),
            "method": "message/stream",
            "params": {
                "task_id": task_id,
                "resubscribe": resubscribe
            }
        }

    # tasks/resubscribe

    def build_tasks_resubscribe(
        self,
        task_id: str,
        stream_id: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build tasks/resubscribe request.

        Args:
            task_id: Task identifier
            stream_id: Stream identifier
            request_id: Optional request ID

        Returns:
            JSON-RPC request dictionary
        """
        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id or self.create_request_id(),
            "method": "tasks/resubscribe",
            "params": {
                "task_id": task_id,
                "stream_id": stream_id
            }
        }

    # Error responses

    def build_error_response(
        self,
        error_code: int,
        error_message: str,
        error_data: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build JSON-RPC error response.

        Args:
            error_code: Error code (negative for server errors)
            error_message: Human-readable error message
            error_data: Additional error context
            request_id: Request ID from original request

        Returns:
            JSON-RPC error response dictionary
        """
        error_response = {
            "code": error_code,
            "message": error_message
        }

        if error_data:
            error_response["data"] = error_data

        return {
            "jsonrpc": self._jsonrpc_version,
            "id": request_id,
            "error": error_response
        }

    # Message utilities

    def parse_message(self, message_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and validate A2A message structure.

        Args:
            message_dict: Raw message dictionary

        Returns:
            Normalized message structure
        """
        role = message_dict.get("role")
        parts = message_dict.get("parts", [])

        # Validate required fields
        if not role:
            raise ValueError("Message missing 'role' field")

        if not isinstance(parts, list):
            raise ValueError("Message 'parts' must be a list")

        # Extract text from parts
        text_parts = [p.get("text", "") for p in parts if p.get("kind") == "text"]
        combined_text = " ".join(text_parts)

        return {
            "role": role,
            "text": combined_text,
            "parts": parts,
            "target": message_dict.get("target"),
            "source": message_dict.get("source")
        }

    def extract_text(self, message: Dict[str, Any]) -> str:
        """
        Extract combined text from A2A message.

        Args:
            message: A2A message structure

        Returns:
            Combined text from all text parts
        """
        parts = message.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if p.get("kind") == "text"]
        return " ".join(text_parts)
