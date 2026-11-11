from __future__ import annotations


class AgentStorageError(Exception):
    """Base class for agent persistence failures."""


class TaskNotFoundError(AgentStorageError):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"task not found: {task_id}")


class DuplicateTaskError(AgentStorageError):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"task already exists: {task_id}")


class ConcurrencyError(AgentStorageError):
    def __init__(
        self,
        task_id: str,
        expected_version: int,
        actual_version: int | None = None,
    ) -> None:
        self.task_id = task_id
        self.expected_version = expected_version
        self.actual_version = actual_version

        message = (
            f"task {task_id} version conflict: expected {expected_version}"
        )
        if actual_version is not None:
            message = f"{message}, found {actual_version}"
        super().__init__(message)
