import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Entitlement(Base):
    """The single access gate for every paid/free path. See section 1 of the plan.

    Scope semantics:
      scope_type='class'      → scope_id=class_id        (single-class purchase)
      scope_type='cohort'     → scope_id=cohort_id       (cohort enrollment)
      scope_type='all_access' → scope_id IS NULL         (active subscription)
    """

    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Partial UNIQUE index: at most one *active* entitlement per
        # (user, scope_type, scope_id). This is the idempotency guard behind the
        # verify + webhook grant race — without it, two near-simultaneous grants
        # can both pass the read-then-insert check in enrollment.py and
        # double-grant (and, for cohorts, double-count a seat). sqlite_where
        # mirrors the predicate so tests on SQLite enforce the same semantics.
        Index(
            "ix_entitlements_active_lookup",
            "user_id",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )
