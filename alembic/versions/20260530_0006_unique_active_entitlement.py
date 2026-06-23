"""make active-entitlement lookup index UNIQUE (idempotency guard)

Promotes ix_entitlements_active_lookup from a plain partial index to a partial
UNIQUE index so that at most one *active* entitlement can exist per
(user_id, scope_type, scope_id). This is the database-level guard behind the
verify + webhook grant race in app/services/enrollment.py: without it, two
near-simultaneous grants could both pass the read-then-insert check and create
duplicate entitlements (and double-count a cohort seat).

Revision ID: 20260530_0006
Revises: 20260530_0005
Create Date: 2026-06-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260530_0006"
down_revision: Union[str, None] = "20260530_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_entitlements_active_lookup", table_name="entitlements")
    op.create_index(
        "ix_entitlements_active_lookup",
        "entitlements",
        ["user_id", "scope_type", "scope_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_entitlements_active_lookup", table_name="entitlements")
    op.create_index(
        "ix_entitlements_active_lookup",
        "entitlements",
        ["user_id", "scope_type", "scope_id"],
        postgresql_where=sa.text("status = 'active'"),
    )
