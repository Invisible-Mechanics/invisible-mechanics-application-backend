"""Recognize deployed database revision.

Revision ID: 20260618_0026
Revises: 20260605_0012
Create Date: 2026-06-22
"""

from collections.abc import Sequence


revision: str = "20260618_0026"
down_revision: str | None = "20260605_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
