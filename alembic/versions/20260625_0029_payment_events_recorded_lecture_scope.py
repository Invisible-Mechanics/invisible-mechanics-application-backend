"""Add payment audit events and recorded lecture payment scope.

Revision ID: 20260625_0029
Revises: 20260623_0028
Create Date: 2026-06-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260625_0029"
down_revision: str | None = "20260623_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id")),
        sa.Column("razorpay_order_id", sa.String(64), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=True),
        sa.Column("razorpay_event_id", sa.String(100), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("razorpay_event_id", name="uq_payment_events_razorpay_event_id"),
    )
    op.create_index(
        "ix_payment_events_payment_created",
        "payment_events",
        ["payment_id", "created_at"],
    )
    op.create_index(
        "ix_payment_events_order_created",
        "payment_events",
        ["razorpay_order_id", "created_at"],
    )
    op.create_index(
        "ix_payments_status_created_at",
        "payments",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_payments_status_created_at", table_name="payments")
    op.drop_index("ix_payment_events_order_created", table_name="payment_events")
    op.drop_index("ix_payment_events_payment_created", table_name="payment_events")
    op.drop_table("payment_events")
