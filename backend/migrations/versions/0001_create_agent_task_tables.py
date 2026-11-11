"""Create agent task and event tables.

Revision ID: 0001_create_agent_task_tables
Revises:
Create Date: 2026-11-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_create_agent_task_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TASK_STATUS_VALUES = (
    "'created', 'planning', 'planned', 'executing', "
    "'waiting_approval', 'paused', 'verifying', 'completed', "
    "'failed', 'cancelled'"
)
_TASK_EVENT_TYPE_VALUES = (
    "'task_created', 'task_transitioned', 'task_paused', "
    "'task_resumed', 'task_failed', 'task_completed', "
    "'task_cancelled'"
)


def upgrade() -> None:
    op.create_table(
        "agent_tasks",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_from", sa.String(length=32), nullable=True),
        sa.Column(
            "iteration_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "tool_call_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_tasks_status",
        ),
        sa.CheckConstraint(
            "paused_from IS NULL OR "
            f"paused_from IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_tasks_paused_from",
        ),
        sa.CheckConstraint(
            "iteration_count >= 0",
            name="ck_agent_tasks_iteration_count",
        ),
        sa.CheckConstraint(
            "tool_call_count >= 0",
            name="ck_agent_tasks_tool_call_count",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_agent_tasks_version",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(
        "ix_agent_tasks_status",
        "agent_tasks",
        ["status"],
    )
    op.create_index(
        "ix_agent_tasks_session_created",
        "agent_tasks",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_agent_tasks_created_at",
        "agent_tasks",
        ["created_at"],
    )

    op.create_table(
        "agent_task_events",
        sa.Column(
            "event_seq",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            f"event_type IN ({_TASK_EVENT_TYPE_VALUES})",
            name="ck_agent_task_events_event_type",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR "
            f"from_status IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_task_events_from_status",
        ),
        sa.CheckConstraint(
            f"to_status IN ({_TASK_STATUS_VALUES})",
            name="ck_agent_task_events_to_status",
        ),
        sa.CheckConstraint(
            "task_version >= 0",
            name="ck_agent_task_events_task_version",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["agent_tasks.task_id"],
            name="fk_agent_task_events_task_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_seq"),
        sa.UniqueConstraint(
            "event_id",
            name="uq_agent_task_events_event_id",
        ),
    )
    op.create_index(
        "ix_agent_task_events_task_seq",
        "agent_task_events",
        ["task_id", "event_seq"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_task_events_task_seq",
        table_name="agent_task_events",
    )
    op.drop_table("agent_task_events")
    op.drop_index("ix_agent_tasks_created_at", table_name="agent_tasks")
    op.drop_index(
        "ix_agent_tasks_session_created",
        table_name="agent_tasks",
    )
    op.drop_index("ix_agent_tasks_status", table_name="agent_tasks")
    op.drop_table("agent_tasks")
