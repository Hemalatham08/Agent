from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

from backend.agent.events import TaskEventType
from backend.agent.models import TaskStatus
from backend.agent.persistence.types import UTCDateTime

_TASK_STATUS_VALUES = ", ".join(
    f"'{status.value}'" for status in TaskStatus
)
_TASK_EVENT_TYPE_VALUES = ", ".join(
    f"'{event_type.value}'" for event_type in TaskEventType
)


def _status_enum(name: str) -> SAEnum:
    return SAEnum(
        TaskStatus,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        length=32,
        values_callable=lambda enum_type: [item.value for item in enum_type],
    )


def _event_type_enum() -> SAEnum:
    return SAEnum(
        TaskEventType,
        name="task_event_type",
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        length=32,
        values_callable=lambda enum_type: [item.value for item in enum_type],
    )


class Base(DeclarativeBase):
    pass


class AgentTaskRecord(Base):
    __tablename__ = "agent_tasks"

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        _status_enum("task_status"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    paused_from: Mapped[TaskStatus | None] = mapped_column(
        _status_enum("paused_from_status"),
        nullable=True,
    )
    iteration_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    tool_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        CheckConstraint(
            f"status IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_tasks_status",
        ),
        CheckConstraint(
            "paused_from IS NULL OR "
            f"paused_from IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_tasks_paused_from",
        ),
        CheckConstraint(
            "iteration_count >= 0",
            name="ck_agent_tasks_iteration_count",
        ),
        CheckConstraint(
            "tool_call_count >= 0",
            name="ck_agent_tasks_tool_call_count",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_agent_tasks_version",
        ),
        Index("ix_agent_tasks_status", "status"),
        Index(
            "ix_agent_tasks_session_created",
            "session_id",
            "created_at",
        ),
        Index("ix_agent_tasks_created_at", "created_at"),
    )


class AgentTaskEventRecord(Base):
    __tablename__ = "agent_task_events"

    event_seq: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[TaskEventType] = mapped_column(
        _event_type_enum(),
        nullable=False,
    )
    from_status: Mapped[TaskStatus | None] = mapped_column(
        _status_enum("event_from_status"),
        nullable=True,
    )
    to_status: Mapped[TaskStatus] = mapped_column(
        _status_enum("event_to_status"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            name="uq_agent_task_events_event_id",
        ),
        CheckConstraint(
            f"event_type IN ({_TASK_EVENT_TYPE_VALUES})",
            name="ck_agent_task_events_event_type",
        ),
        CheckConstraint(
            "from_status IS NULL OR "
            f"from_status IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_task_events_from_status",
        ),
        CheckConstraint(
            f"to_status IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_task_events_to_status",
        ),
        CheckConstraint(
            "task_version >= 0",
            name="ck_agent_task_events_task_version",
        ),
        Index(
            "ix_agent_task_events_task_seq",
            "task_id",
            "event_seq",
        ),
    )
