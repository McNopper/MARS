"""
A2A Task Manager

Manages A2A task lifecycle for agent-to-agent communication.
Handles task creation, execution, cancellation, and state tracking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List
from uuid import uuid4


class TaskState(Enum):
    """A2A task lifecycle states"""
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    AUTH_REQUIRED = "auth_required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class A2ATask:
    """A2A Task representation"""
    task_id: str
    message: Dict[str, Any]
    state: TaskState = TaskState.SUBMITTED
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Task metadata
    source_agent: Optional[str] = None
    target_agent: Optional[str] = None
    parent_task_id: Optional[str] = None

    # Streaming support
    stream_subscribers: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary representation"""
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "parent_task_id": self.parent_task_id
        }


class A2ATaskManager:
    """
    Manages A2A task lifecycle and state.

    Provides:
    - Task creation and tracking
    - State transitions
    - Result storage
    - Streaming support
    - Task cancellation
    """

    def __init__(self):
        self._tasks: Dict[str, A2ATask] = {}
        self._agent_tasks: Dict[str, List[str]] = {}  # agent_id -> [task_ids]
        self._streams: Dict[str, Any] = {}  # task_id -> stream_id
        self._lock = asyncio.Lock()

    async def create_task(
        self,
        task_id: str,
        message: Dict[str, Any],
        source_agent: Optional[str] = None,
        target_agent: Optional[str] = None,
        parent_task_id: Optional[str] = None
    ) -> A2ATask:
        """
        Create a new A2A task.

        Args:
            task_id: Unique task identifier
            message: A2A message that created this task
            source_agent: Agent that initiated the task
            target_agent: Agent that will execute the task
            parent_task_id: Parent task ID if this is a subtask

        Returns:
            Created A2ATask
        """
        async with self._lock:
            if task_id in self._tasks:
                raise ValueError(f"Task already exists: {task_id}")

            task = A2ATask(
                task_id=task_id,
                message=message,
                source_agent=source_agent,
                target_agent=target_agent,
                parent_task_id=parent_task_id
            )

            self._tasks[task_id] = task

            # Track tasks by agent
            if source_agent:
                if source_agent not in self._agent_tasks:
                    self._agent_tasks[source_agent] = []
                self._agent_tasks[source_agent].append(task_id)

            if target_agent:
                if target_agent not in self._agent_tasks:
                    self._agent_tasks[target_agent] = []
                self._agent_tasks[target_agent].append(task_id)

            return task

    async def get_task(self, task_id: str) -> Optional[A2ATask]:
        """
        Get task by ID.

        Args:
            task_id: Task identifier

        Returns:
            A2ATask or None if not found
        """
        return self._tasks.get(task_id)

    async def update_task_state(
        self,
        task_id: str,
        new_state: TaskState,
        result: Optional[Any] = None,
        error: Optional[Dict[str, Any]] = None
    ) -> Optional[A2ATask]:
        """
        Update task state and result.

        Args:
            task_id: Task identifier
            new_state: New task state
            result: Task result (for completed tasks)
            error: Task error (for failed tasks)

        Returns:
            Updated A2ATask or None if not found
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            # Validate state transition
            if not self._is_valid_state_transition(task.state, new_state):
                raise ValueError(
                    f"Invalid state transition: {task.state.value} -> {new_state.value}"
                )

            task.state = new_state
            task.updated_at = datetime.utcnow()

            if result is not None:
                task.result = result

            if error is not None:
                task.error = error

            # Set completion time for terminal states
            if new_state in [TaskState.COMPLETED, TaskState.CANCELED, TaskState.REJECTED, TaskState.FAILED]:
                task.completed_at = datetime.utcnow()

            # Notify stream subscribers
            await self._notify_task_update(task)

            return task

    async def cancel_task(self, task_id: str) -> Optional[A2ATask]:
        """
        Cancel a task.

        Args:
            task_id: Task identifier

        Returns:
            Canceled A2ATask or None if not found
        """
        return await self.update_task_state(task_id, TaskState.CANCELED)

    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task from tracking.

        Args:
            task_id: Task identifier

        Returns:
            True if task was deleted, False if not found
        """
        async with self._lock:
            task = self._tasks.pop(task_id, None)
            if not task:
                return False

            # Remove from agent task lists
            if task.source_agent and task.source_agent in self._agent_tasks:
                self._agent_tasks[task.source_agent].remove(task_id)

            if task.target_agent and task.target_agent in self._agent_tasks:
                self._agent_tasks[task.target_agent].remove(task_id)

            # Clean up streams
            self._streams.pop(task_id, None)

            return True

    async def get_agent_tasks(self, agent_id: str) -> List[A2ATask]:
        """
        Get all tasks for a specific agent.

        Args:
            agent_id: Agent identifier

        Returns:
            List of A2ATask for the agent
        """
        task_ids = self._agent_tasks.get(agent_id, [])
        tasks = []
        for task_id in task_ids:
            task = await self.get_task(task_id)
            if task:
                tasks.append(task)
        return tasks

    async def get_active_tasks(self) -> List[A2ATask]:
        """
        Get all active (non-terminal) tasks.

        Returns:
            List of active A2ATask
        """
        terminal_states = {
            TaskState.COMPLETED,
            TaskState.CANCELED,
            TaskState.REJECTED,
            TaskState.FAILED
        }

        active_tasks = []
        for task in self._tasks.values():
            if task.state not in terminal_states:
                active_tasks.append(task)

        return active_tasks

    async def create_task_stream(self, task_id: str, session: Any) -> str:
        """
        Create SSE stream for task updates.

        Args:
            task_id: Task identifier
            session: Client session for streaming

        Returns:
            Stream URL
        """
        stream_id = str(uuid4())
        self._streams[task_id] = {
            "stream_id": stream_id,
            "session": session,
            "created_at": datetime.utcnow()
        }

        # Add session as stream subscriber
        task = await self.get_task(task_id)
        if task:
            task.stream_subscribers.append(session)

        return f"/tasks/{task_id}/stream/{stream_id}"

    async def resubscribe_stream(self, task_id: str, stream_id: str, session: Any) -> str:
        """
        Resume existing stream connection.

        Args:
            task_id: Task identifier
            stream_id: Existing stream identifier
            session: Client session for streaming

        Returns:
            Stream URL
        """
        # Verify stream exists
        if task_id not in self._streams:
            raise ValueError(f"No stream found for task: {task_id}")

        stream_data = self._streams[task_id]
        if stream_data["stream_id"] != stream_id:
            raise ValueError(f"Stream ID mismatch: {stream_id}")

        # Update session
        stream_data["session"] = session

        # Add session as stream subscriber if not already
        task = await self.get_task(task_id)
        if task and session not in task.stream_subscribers:
            task.stream_subscribers.append(session)

        return f"/tasks/{task_id}/stream/{stream_id}"

    async def _notify_task_update(self, task: A2ATask) -> None:
        """Notify stream subscribers of task update"""
        for subscriber in task.stream_subscribers:
            try:
                # Send update to subscriber
                if hasattr(subscriber, 'send_task_update'):
                    await subscriber.send_task_update(task.to_dict())
            except Exception as e:
                # Log error but continue notifying other subscribers
                print(f"Error notifying task subscriber: {e}")

    def _is_valid_state_transition(self, current_state: TaskState, new_state: TaskState) -> bool:
        """Validate A2A task state transitions"""
        valid_transitions = {
            TaskState.SUBMITTED: [TaskState.WORKING, TaskState.REJECTED, TaskState.FAILED],
            TaskState.WORKING: [
                TaskState.INPUT_REQUIRED,
                TaskState.AUTH_REQUIRED,
                TaskState.COMPLETED,
                TaskState.CANCELED,
                TaskState.FAILED
            ],
            TaskState.INPUT_REQUIRED: [TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED],
            TaskState.AUTH_REQUIRED: [TaskState.WORKING, TaskState.CANCELED, TaskState.FAILED],
            # Terminal states have no valid transitions
            TaskState.COMPLETED: [],
            TaskState.CANCELED: [],
            TaskState.REJECTED: [],
            TaskState.FAILED: [],
        }

        return new_state in valid_transitions.get(current_state, [])

    async def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """
        Clean up old completed tasks.

        Args:
            max_age_hours: Maximum age in hours for task retention

        Returns:
            Number of tasks cleaned up
        """
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        cleaned = 0

        async with self._lock:
            tasks_to_delete = []
            for task_id, task in self._tasks.items():
                if (
                    task.state in [TaskState.COMPLETED, TaskState.CANCELED, TaskState.REJECTED, TaskState.FAILED] and
                    task.completed_at and
                    task.completed_at < cutoff
                ):
                    tasks_to_delete.append(task_id)

            for task_id in tasks_to_delete:
                if await self.delete_task(task_id):
                    cleaned += 1

        return cleaned
