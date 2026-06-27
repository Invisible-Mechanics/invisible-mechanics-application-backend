"""Track masterclass funnel events.

Revision ID: 20260627_0031
Revises: 20260625_0030
"""

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260627_0031"
down_revision: Union[str, None] = "20260625_0030"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.create_table(
        "masterclass_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", sa.String(length=80), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("path", sa.String(length=500), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_masterclass_events_visitor_id",
        "masterclass_events",
        ["visitor_id"],
    )
    op.create_index(
        "ix_masterclass_events_type_created",
        "masterclass_events",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_masterclass_events_user_created",
        "masterclass_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_masterclass_events_user_created", table_name="masterclass_events")
    op.drop_index("ix_masterclass_events_type_created", table_name="masterclass_events")
    op.drop_index("ix_masterclass_events_visitor_id", table_name="masterclass_events")
    op.drop_table("masterclass_events")
