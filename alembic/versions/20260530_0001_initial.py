"""initial schema (phase 0)

Revision ID: 20260530_0001
Revises:
Create Date: 2026-05-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260530_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="student"),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_phone", "users", ["phone"])

    op.create_table(
        "cohorts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("early_bird_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("early_bird_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seat_limit", sa.Integer, nullable=True),
        sa.Column("seats_taken", sa.Integer, nullable=False, server_default="0"),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("subject", sa.String(50), nullable=True),
        sa.Column("topic", sa.String(200), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_min", sa.Integer, nullable=False, server_default="60"),
        sa.Column("access_type", sa.String(20), nullable=False, server_default="free"),
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id"),
            nullable=True,
        ),
        sa.Column("price_single", sa.Numeric(10, 2), nullable=True),
        sa.Column("zoom_meeting_id", sa.String(50), nullable=True),
        sa.Column("zoom_join_url", sa.String(500), nullable=True),
        sa.Column("zoom_password", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="scheduled"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "entitlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_entitlements_active_lookup",
        "entitlements",
        ["user_id", "scope_type", "scope_id"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "recordings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("classes.id"),
            nullable=False,
        ),
        sa.Column("storage_url", sa.String(1000), nullable=True),
        sa.Column("duration_sec", sa.Integer, nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="processing"),
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("recordings")
    op.drop_index("ix_entitlements_active_lookup", table_name="entitlements")
    op.drop_table("entitlements")
    op.drop_table("classes")
    op.drop_table("cohorts")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
