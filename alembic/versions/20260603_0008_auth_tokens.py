"""auth_tokens: magic-link + 6-digit code rows

Stores one row per outstanding login challenge. Only hashes are persisted;
raw values live in the email or the user's hand. Rows are one-shot —
consumed_at is stamped on first successful verify.

Revision ID: 20260603_0008
Revises: 20260603_0007
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_0008"
down_revision: Union[str, None] = "20260603_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("next_path", sa.String(500), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_auth_tokens_email_created_at", "auth_tokens", ["email", "created_at"]
    )
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_token_hash", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_email_created_at", table_name="auth_tokens")
    op.drop_table("auth_tokens")
