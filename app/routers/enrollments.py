"""Paid purchases (cohort enrollment & single class) via Razorpay one-time payments.

Endpoints:
  POST /enrollments/cohorts/{id}/order  (auth) — create a Razorpay order for a cohort
  POST /enrollments/classes/{id}/order  (auth) — create a Razorpay order for one class
  POST /enrollments/verify              (auth) — verify the Checkout signature, grant access
  POST /webhooks/razorpay               (no auth) — server-to-server source of truth

The webhook router declares no `current_user` dependency, so it is unauthenticated
(verified instead by the Razorpay webhook signature). There is no app-wide auth.
"""

import json
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import Class, Cohort, Entitlement, Payment, RecordedLecture, User
from app.schemas import (
    CreateOrderResponse,
    PurchaseOut,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from app.services.access import can_access, can_access_recorded
from app.services.enrollment import (
    grant_entitlement,
    record_payment_event,
    record_payment_event_best_effort,
)
from app.services.invoice import send_invoice_email_best_effort
from app.services.razorpay import (
    RazorpayClient,
    class_price_paise,
    effective_price_paise,
    get_razorpay_client,
    single_content_price_paise,
    verify_payment_signature,
    verify_webhook_signature,
)

router = APIRouter(prefix="/enrollments", tags=["enrollments"])
webhook_router = APIRouter(tags=["webhooks"])


async def _is_enrolled_in_cohort(db: AsyncSession, user_id: uuid.UUID, cohort_id: uuid.UUID) -> bool:
    now = datetime.now(UTC)
    stmt = (
        select(Entitlement.id)
        .where(
            Entitlement.user_id == user_id,
            Entitlement.status == "active",
            or_(Entitlement.valid_until.is_(None), Entitlement.valid_until > now),
            or_(
                Entitlement.scope_type == "all_access",
                (Entitlement.scope_type == "cohort") & (Entitlement.scope_id == cohort_id),
            ),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


@router.post("/cohorts/{cohort_id}/order", response_model=CreateOrderResponse)
async def create_cohort_order(
    cohort_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    rzp: RazorpayClient = Depends(get_razorpay_client),
) -> CreateOrderResponse:
    cohort = await db.get(Cohort, cohort_id)
    if cohort is None:
        raise HTTPException(status_code=404, detail="cohort not found")
    if cohort.status != "open":
        raise HTTPException(status_code=409, detail="cohort is not open for enrollment")

    if await _is_enrolled_in_cohort(db, user.id, cohort_id):
        raise HTTPException(status_code=409, detail="already enrolled")

    if cohort.seat_limit is not None and cohort.seats_taken >= cohort.seat_limit:
        raise HTTPException(status_code=409, detail="cohort is full")

    amount = effective_price_paise(cohort)
    if amount is None:
        raise HTTPException(status_code=409, detail="cohort is not purchasable")

    # Razorpay caps `receipt` at 40 chars, so we can't fit two full UUIDs.
    # The full ids live in `notes`; the receipt is just a short human reference.
    receipt = f"coh_{cohort_id.hex[:10]}_{user.id.hex[:10]}"
    try:
        order = await rzp.create_order(
            amount=amount,
            currency="INR",
            receipt=receipt,
            notes={"cohort_id": str(cohort_id), "user_id": str(user.id)},
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="payment provider error")

    payment = Payment(
        user_id=user.id,
        scope_type="cohort",
        scope_id=cohort_id,
        razorpay_order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        status="created",
    )
    response = CreateOrderResponse(
        order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        key_id=get_settings().razorpay_key_id,
        title=cohort.title,
        prefill_name=user.name,
        prefill_email=user.email,
        prefill_contact=user.phone,
    )

    db.add(payment)
    try:
        await db.commit()
    except IntegrityError:
        # Same order id already recorded (deterministic fake id / retry) — reuse it.
        await db.rollback()
    else:
        await record_payment_event_best_effort(
            db,
            payment=payment,
            event_type="order_created",
            source="api",
            payload={"scope_type": "cohort", "scope_id": str(cohort_id)},
        )

    return response


@router.post("/classes/{class_id}/order", response_model=CreateOrderResponse)
async def create_class_order(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    rzp: RazorpayClient = Depends(get_razorpay_client),
) -> CreateOrderResponse:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    if klass.access_type != "paid":
        raise HTTPException(status_code=409, detail="lecture is not purchasable")
    if klass.status == "ended":
        raise HTTPException(status_code=409, detail="lecture has ended")

    # can_access covers free, single-class, cohort, and all_access — if it's
    # already true, there's nothing to buy.
    if await can_access(db, user, klass):
        raise HTTPException(status_code=409, detail="already have access")

    amount = class_price_paise(klass)
    if amount is None:
        raise HTTPException(status_code=409, detail="lecture is not purchasable")

    receipt = f"cls_{class_id.hex[:10]}_{user.id.hex[:10]}"
    try:
        order = await rzp.create_order(
            amount=amount,
            currency="INR",
            receipt=receipt,
            notes={"class_id": str(class_id), "user_id": str(user.id)},
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="payment provider error")

    payment = Payment(
        user_id=user.id,
        scope_type="class",
        scope_id=class_id,
        razorpay_order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        status="created",
    )
    response = CreateOrderResponse(
        order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        key_id=get_settings().razorpay_key_id,
        title=klass.title,
        prefill_name=user.name,
        prefill_email=user.email,
        prefill_contact=user.phone,
    )

    db.add(payment)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    else:
        await record_payment_event_best_effort(
            db,
            payment=payment,
            event_type="order_created",
            source="api",
            payload={"scope_type": "class", "scope_id": str(class_id)},
        )

    return response


@router.get("/purchases", response_model=list[PurchaseOut])
async def list_my_purchases(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> list[Payment]:
    stmt = (
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.created_at.desc())
        .limit(100)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("/lectures/{lecture_id}/order", response_model=CreateOrderResponse)
async def create_recorded_lecture_order(
    lecture_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    rzp: RazorpayClient = Depends(get_razorpay_client),
) -> CreateOrderResponse:
    lecture = await db.get(RecordedLecture, lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="recorded lecture not found")
    if lecture.access_type != "paid":
        raise HTTPException(status_code=409, detail="lecture is not purchasable")

    if await can_access_recorded(db, user, lecture):
        raise HTTPException(status_code=409, detail="already have access")

    amount = single_content_price_paise(lecture)
    if amount is None:
        raise HTTPException(status_code=409, detail="lecture is not purchasable")

    receipt = f"vid_{lecture_id.hex[:10]}_{user.id.hex[:10]}"
    try:
        order = await rzp.create_order(
            amount=amount,
            currency="INR",
            receipt=receipt,
            notes={"lecture_id": str(lecture_id), "user_id": str(user.id)},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="payment provider error") from exc

    payment = Payment(
        user_id=user.id,
        scope_type="recorded_lecture",
        scope_id=lecture_id,
        razorpay_order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        status="created",
    )
    response = CreateOrderResponse(
        order_id=order.order_id,
        amount=order.amount,
        currency=order.currency,
        key_id=get_settings().razorpay_key_id,
        title=lecture.title,
        prefill_name=user.name,
        prefill_email=user.email,
        prefill_contact=user.phone,
    )

    db.add(payment)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
    else:
        await record_payment_event_best_effort(
            db,
            payment=payment,
            event_type="order_created",
            source="api",
            payload={"scope_type": "recorded_lecture", "scope_id": str(lecture_id)},
        )

    return response


@router.post("/verify", response_model=VerifyPaymentResponse)
async def verify_payment(
    body: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> VerifyPaymentResponse:
    secret = get_settings().razorpay_key_secret
    if not verify_payment_signature(
        order_id=body.razorpay_order_id,
        payment_id=body.razorpay_payment_id,
        signature=body.razorpay_signature,
        secret=secret,
    ):
        raise HTTPException(status_code=400, detail="invalid payment signature")

    payment = (
        await db.execute(
            select(Payment).where(Payment.razorpay_order_id == body.razorpay_order_id)
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="order not found")
    if payment.user_id != user.id:
        raise HTTPException(status_code=403, detail="order does not belong to you")

    was_paid = payment.status == "paid"
    payment.razorpay_payment_id = body.razorpay_payment_id
    await grant_entitlement(db, payment)
    await record_payment_event_best_effort(
        db,
        payment=payment,
        event_type="payment_verified",
        source="api",
        payload={"razorpay_payment_id": body.razorpay_payment_id},
    )
    if payment.status == "paid" and not was_paid:
        await send_invoice_email_best_effort(db, payment)
    return VerifyPaymentResponse(status="enrolled")


@webhook_router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    secret = get_settings().razorpay_webhook_secret
    if not secret:
        # No webhook configured yet (pre-dashboard window). Ignore safely.
        return {"ok": False, "reason": "webhook secret not configured"}

    if not verify_webhook_signature(raw_body=raw, signature=signature, secret=secret):
        raise HTTPException(status_code=400, detail="invalid webhook signature")

    event = json.loads(raw)
    event_name = str(event.get("event", "unknown"))
    event_id = event.get("id")

    if event_id:
        try:
            record_payment_event(
                db,
                payment=None,
                event_type=event_name,
                source="webhook",
                payload=event,
                razorpay_event_id=str(event_id),
            )
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return {"ok": True, "duplicate": True}
        except SQLAlchemyError:
            await db.rollback()

    if event_name not in ("payment.captured", "order.paid"):
        await db.commit()
        return {"ok": True, "ignored": True}

    payload = event.get("payload", {})
    order_id = (
        payload.get("payment", {}).get("entity", {}).get("order_id")
        or payload.get("order", {}).get("entity", {}).get("id")
    )
    payment_id = payload.get("payment", {}).get("entity", {}).get("id")
    if not order_id:
        await db.commit()
        return {"ok": True, "ignored": True}

    payment = (
        await db.execute(select(Payment).where(Payment.razorpay_order_id == order_id))
    ).scalar_one_or_none()
    if payment is None:
        # Unknown order: nothing to grant. 200 so Razorpay stops retrying.
        await db.commit()
        return {"ok": True, "ignored": True}

    was_paid = payment.status == "paid"
    if payment_id:
        payment.razorpay_payment_id = payment_id
    await grant_entitlement(db, payment)
    await record_payment_event_best_effort(
        db,
        payment=payment,
        event_type=event_name,
        source="webhook",
        payload={"razorpay_order_id": order_id, "razorpay_payment_id": payment_id},
    )
    if payment.status == "paid" and not was_paid:
        await send_invoice_email_best_effort(db, payment)
    return {"ok": True}
