"""Idempotent entitlement granting for paid purchases.

Shared by both the /verify endpoint (browser happy path) and the webhook
(server-to-server source of truth). Either path may arrive first; the second
is a no-op. Cohort seat counting is oversell-safe via a single conditional UPDATE.
"""

import json
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Cohort, Entitlement, Payment, PaymentEvent


def record_payment_event(
    db: AsyncSession,
    *,
    payment: Payment | None,
    event_type: str,
    source: str,
    payload: dict | None = None,
    razorpay_event_id: str | None = None,
) -> None:
    db.add(
        PaymentEvent(
            payment_id=payment.id if payment else None,
            razorpay_order_id=payment.razorpay_order_id if payment else None,
            razorpay_payment_id=payment.razorpay_payment_id if payment else None,
            razorpay_event_id=razorpay_event_id,
            event_type=event_type,
            source=source,
            payload_json=json.dumps(payload, default=str) if payload is not None else None,
        )
    )


async def _has_active_entitlement(
    db: AsyncSession, user_id: uuid.UUID, scope_type: str, scope_id: uuid.UUID
) -> bool:
    stmt = (
        select(Entitlement.id)
        .where(
            Entitlement.user_id == user_id,
            Entitlement.scope_type == scope_type,
            Entitlement.scope_id == scope_id,
            Entitlement.status == "active",
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def grant_entitlement(db: AsyncSession, payment: Payment) -> None:
    """Grant access for a paid order. Dispatches on scope_type. Idempotent."""
    if payment.scope_type == "cohort":
        await grant_cohort_entitlement(db, payment)
    elif payment.scope_type == "class":
        await grant_class_entitlement(db, payment)
    elif payment.scope_type == "recorded_lecture":
        await grant_recorded_lecture_entitlement(db, payment)
    else:  # pragma: no cover - guard against a malformed payment row
        raise ValueError(f"unknown payment scope_type: {payment.scope_type}")


async def grant_cohort_entitlement(db: AsyncSession, payment: Payment) -> None:
    """Grant a cohort entitlement for a paid order. Safe to call more than once."""
    # (1) Already granted? (verify+webhook race, or webhook re-delivery) -> no-op.
    if await _has_active_entitlement(db, payment.user_id, "cohort", payment.scope_id):
        payment.status = "paid"
        await db.commit()
        return

    # (2) Atomic, oversell-safe seat increment. Works on Postgres and SQLite
    # (single statement) — no SELECT ... FOR UPDATE needed.
    res = await db.execute(
        update(Cohort)
        .where(Cohort.id == payment.scope_id)
        .where((Cohort.seat_limit.is_(None)) | (Cohort.seats_taken < Cohort.seat_limit))
        .values(seats_taken=Cohort.seats_taken + 1)
    )
    if res.rowcount == 0:
        # Cap filled after the student already paid. Grant-and-flag (refunds are
        # manual) — the educator expands the cohort or refunds out of band.
        await db.execute(
            update(Cohort)
            .where(Cohort.id == payment.scope_id)
            .values(seats_taken=Cohort.seats_taken + 1)
        )
        payment.oversold = True

    # (3) Write the entitlement — the one access gate.
    db.add(
        Entitlement(
            user_id=payment.user_id,
            scope_type="cohort",
            scope_id=payment.scope_id,
            source="razorpay",
            status="active",
        )
    )
    payment.status = "paid"
    record_payment_event(
        db,
        payment=payment,
        event_type="entitlement_granted",
        source="system",
        payload={"scope_type": "cohort", "scope_id": str(payment.scope_id)},
    )
    try:
        await db.commit()
    except IntegrityError:
        # Lost the verify/webhook race: another grant for this (user, cohort)
        # committed first and the partial-unique index rejected our duplicate.
        # Roll back this whole transaction — including the seat increment above —
        # and record the payment as paid. The winner already counted the seat.
        await db.rollback()
        payment.status = "paid"
        await db.commit()


async def grant_class_entitlement(db: AsyncSession, payment: Payment) -> None:
    """Grant a single-class entitlement for a paid order. Safe to call more than once."""
    if await _has_active_entitlement(db, payment.user_id, "class", payment.scope_id):
        payment.status = "paid"
        await db.commit()
        return

    db.add(
        Entitlement(
            user_id=payment.user_id,
            scope_type="class",
            scope_id=payment.scope_id,
            source="razorpay",
            status="active",
        )
    )
    payment.status = "paid"
    record_payment_event(
        db,
        payment=payment,
        event_type="entitlement_granted",
        source="system",
        payload={"scope_type": "class", "scope_id": str(payment.scope_id)},
    )
    try:
        await db.commit()
    except IntegrityError:
        # Lost the verify/webhook race (see grant_cohort_entitlement). The winner
        # already wrote the entitlement; absorb the duplicate as a no-op.
        await db.rollback()
        payment.status = "paid"
        await db.commit()


async def grant_recorded_lecture_entitlement(db: AsyncSession, payment: Payment) -> None:
    """Grant a single recorded-lecture entitlement. Safe to call more than once."""
    if await _has_active_entitlement(
        db, payment.user_id, "recorded_lecture", payment.scope_id
    ):
        payment.status = "paid"
        await db.commit()
        return

    db.add(
        Entitlement(
            user_id=payment.user_id,
            scope_type="recorded_lecture",
            scope_id=payment.scope_id,
            source="razorpay",
            status="active",
        )
    )
    payment.status = "paid"
    record_payment_event(
        db,
        payment=payment,
        event_type="entitlement_granted",
        source="system",
        payload={"scope_type": "recorded_lecture", "scope_id": str(payment.scope_id)},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        payment.status = "paid"
        await db.commit()
