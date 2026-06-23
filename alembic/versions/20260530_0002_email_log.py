"""email_log dedup table

Revision ID: 20260530_0002
Revises: 20260530_0001
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260530_0002"
down_revision: Union[str, None] = "20260530_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "class_id", "kind", name="uq_email_log_user_class_kind"),
    )


def downgrade() -> None:
    op.drop_table("email_log")
