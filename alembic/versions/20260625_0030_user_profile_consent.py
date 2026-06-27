"""Add student profile and consent fields.

Revision ID: 20260625_0030
Revises: 20260625_0029
Create Date: 2026-06-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260625_0030"
down_revision: str | None = "20260625_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS target_exam VARCHAR(10)")
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS grade VARCHAR(20)")
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP WITH TIME ZONE")
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMP WITH TIME ZONE")
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP WITH TIME ZONE")
        op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_version VARCHAR(40)")
        return

    op.add_column("users", sa.Column("target_exam", sa.String(10), nullable=True))
    op.add_column("users", sa.Column("grade", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("consent_version", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "consent_version")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "grade")
    op.drop_column("users", "target_exam")
