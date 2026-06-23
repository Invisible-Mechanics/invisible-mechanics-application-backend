import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Payment(Base):
    """One row per Razorpay order. The ledger behind every one-time payment.

    Generalises beyond cohorts: scope_type='cohort' now, 'class' later (pay-per-class).
    razorpay_order_id is UNIQUE — it is the idempotency anchor that both the
    /verify endpoint and the webhook look up by, so a payment is granted exactly once.
    `amount` is in paise (integer), matching exactly what Razorpay charges.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'cohort' | 'class'
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64))

    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # paise
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="created", nullable=False)
    # created | paid | failed
    oversold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("razorpay_order_id", name="uq_payments_razorpay_order_id"),
        Index("ix_payments_user_scope", "user_id", "scope_type", "scope_id"),
    )
