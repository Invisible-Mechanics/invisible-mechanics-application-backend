"""Repair live schema drift.

Revision ID: 20260623_0027
Revises: 20260618_0026
Create Date: 2026-06-23
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260623_0027"
down_revision: str | None = "20260618_0026"
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
                  AND column_name = 'token_hash'
            ) THEN
                ALTER TABLE auth_tokens ADD COLUMN token_hash varchar(64);
                UPDATE auth_tokens
                SET token_hash = COALESCE(code_hash, repeat('0', 64))
                WHERE token_hash IS NULL;
                ALTER TABLE auth_tokens ALTER COLUMN token_hash SET NOT NULL;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'auth_tokens'
                  AND column_name = 'token_hash'
            )
            AND NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'auth_tokens'
                  AND indexname = 'ix_auth_tokens_token_hash'
            ) THEN
                CREATE INDEX ix_auth_tokens_token_hash ON auth_tokens (token_hash);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            fallback_cohort uuid;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'recorded_lectures'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'recorded_lectures'
                  AND column_name = 'cohort_id'
            ) THEN
                ALTER TABLE recorded_lectures ADD COLUMN cohort_id uuid;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'recorded_lectures'
                  AND column_name = 'cohort_id'
            ) THEN
                SELECT id INTO fallback_cohort
                FROM cohorts
                ORDER BY created_at ASC
                LIMIT 1;

                IF fallback_cohort IS NULL THEN
                    fallback_cohort := '00000000-0000-0000-0000-000000000027'::uuid;
                    INSERT INTO cohorts (
                        id,
                        title,
                        description,
                        seats_taken,
                        status,
                        created_at
                    )
                    VALUES (
                        fallback_cohort,
                        'Imported recordings',
                        'Automatically created for recordings imported from the previous schema.',
                        0,
                        'open',
                        now()
                    )
                    ON CONFLICT (id) DO NOTHING;
                END IF;

                UPDATE recorded_lectures
                SET cohort_id = fallback_cohort
                WHERE cohort_id IS NULL;

                ALTER TABLE recorded_lectures ALTER COLUMN cohort_id SET NOT NULL;

                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'recorded_lectures_cohort_id_fkey'
                      AND conrelid = 'recorded_lectures'::regclass
                ) THEN
                    ALTER TABLE recorded_lectures
                    ADD CONSTRAINT recorded_lectures_cohort_id_fkey
                    FOREIGN KEY (cohort_id) REFERENCES cohorts(id);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'recorded_lectures'
                      AND indexname = 'ix_recorded_lectures_cohort_recorded_on'
                ) THEN
                    CREATE INDEX ix_recorded_lectures_cohort_recorded_on
                    ON recorded_lectures (cohort_id, recorded_on);
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
