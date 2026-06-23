"""payments ledger for one-time Razorpay orders

Revision ID: 20260530_0005
Revises: 20260530_0004
Create Date: 2026-05-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20260530_0005"
down_revision: Union[str, None] = "20260530_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", UUID(as_uuid=True), nullable=False),
        sa.Column("razorpay_order_id", sa.String(64), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=True),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        sa.Column("oversold", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("razorpay_order_id", name="uq_payments_razorpay_order_id"),
    )
    op.create_index("ix_payments_user_scope", "payments", ["user_id", "scope_type", "scope_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_user_scope", table_name="payments")
    op.drop_table("payments")
