import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Cohort, Entitlement, Payment, PaymentEvent

WEBHOOK_SECRET = "test-webhook-secret"  # matches conftest


def _sign_raw(raw: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()


async def _seed_payment(session, test_user) -> tuple[uuid.UUID, str]:
    cohort = Cohort(
        id=uuid.uuid4(), title="Webhook cohort", seat_limit=50, status="open"
    )
    payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort.id,
        razorpay_order_id="order_WEBHOOK",
        amount=99900,
        currency="INR",
        status="created",
    )
    session.add_all([cohort, payment])
    await session.commit()
    return cohort.id, payment.razorpay_order_id


def _event(order_id: str) -> bytes:
    return json.dumps(
        {
            "id": "evt_WEBHOOK",
            "event": "payment.captured",
            "payload": {
                "payment": {"entity": {"id": "pay_WEBHOOK", "order_id": order_id}}
            },
        }
    ).encode()


@pytest.mark.asyncio
async def test_webhook_grants_entitlement(client, session, test_user):
    cohort_id, order_id = await _seed_payment(session, test_user)
    raw = _event(order_id)

    r = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"X-Razorpay-Signature": _sign_raw(raw), "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    ent_count = (
        await session.execute(
            select(func.count()).select_from(Entitlement).where(Entitlement.scope_id == cohort_id)
        )
    ).scalar_one()
    assert ent_count == 1

    cohort = await session.get(Cohort, cohort_id)
    await session.refresh(cohort)
    assert cohort.seats_taken == 1

    event_count = (
        await session.execute(
            select(func.count())
            .select_from(PaymentEvent)
            .where(PaymentEvent.razorpay_event_id == "evt_WEBHOOK")
        )
    ).scalar_one()
    assert event_count == 1


@pytest.mark.asyncio
async def test_webhook_is_idempotent(client, session, test_user):
    cohort_id, order_id = await _seed_payment(session, test_user)
    raw = _event(order_id)
    headers = {"X-Razorpay-Signature": _sign_raw(raw), "Content-Type": "application/json"}

    assert client.post("/webhooks/razorpay", content=raw, headers=headers).status_code == 200
    assert client.post("/webhooks/razorpay", content=raw, headers=headers).status_code == 200

    ent_count = (
        await session.execute(
            select(func.count()).select_from(Entitlement).where(Entitlement.scope_id == cohort_id)
        )
    ).scalar_one()
    assert ent_count == 1

    cohort = await session.get(Cohort, cohort_id)
    await session.refresh(cohort)
    assert cohort.seats_taken == 1


@pytest.mark.asyncio
async def test_webhook_bad_signature_400(client, session, test_user):
    _, order_id = await _seed_payment(session, test_user)
    raw = _event(order_id)
    r = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"X-Razorpay-Signature": "wrong", "Content-Type": "application/json"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_unknown_order_ignored(client, session, test_user):
    raw = _event("order_DOES_NOT_EXIST")
    r = client.post(
        "/webhooks/razorpay",
        content=raw,
        headers={"X-Razorpay-Signature": _sign_raw(raw), "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json().get("ignored") is True
