"""Add SMS OTP auth token columns.

Revision ID: 20260623_0028
Revises: 20260623_0027
Create Date: 2026-06-23
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260623_0028"
down_revision: str | None = "20260623_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'auth_tokens'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'auth_tokens'
                  AND column_name = 'channel'
            ) THEN
                ALTER TABLE auth_tokens ADD COLUMN channel varchar(20) NOT NULL DEFAULT 'email';
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'auth_tokens'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'auth_tokens'
                  AND column_name = 'phone'
            ) THEN
                ALTER TABLE auth_tokens ADD COLUMN phone varchar(20);
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'auth_tokens'
                  AND column_name = 'phone'
            )
            AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'auth_tokens'
                  AND indexname = 'ix_auth_tokens_phone_created_at'
            ) THEN
                CREATE INDEX ix_auth_tokens_phone_created_at ON auth_tokens (phone, created_at);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
