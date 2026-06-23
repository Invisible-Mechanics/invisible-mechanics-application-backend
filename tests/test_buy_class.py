import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Class, Entitlement, Payment
from app.services.razorpay import _sign

SECRET = "test-secret"  # matches conftest RAZORPAY_KEY_SECRET


def _paid_class(cohort_id, **overrides) -> Class:
    return Class(
        id=uuid.uuid4(),
        title=overrides.pop("title", "Modern Physics — Single"),
        scheduled_start=datetime.now(UTC) + timedelta(days=2),
        duration_min=90,
        access_type=overrides.pop("access_type", "paid"),
        price_single=overrides.pop("price_single", Decimal("499.00")),
        status=overrides.pop("status", "scheduled"),
        cohort_id=cohort_id,
        **overrides,
    )


@pytest.mark.asyncio
async def test_create_class_order(client, session, cohort):
    klass = _paid_class(cohort.id)
    session.add(klass)
    await session.commit()

    r = client.post(f"/enrollments/classes/{klass.id}/order")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 49900  # paise
    assert body["title"] == "Modern Physics — Single"

    payment = (
        await session.execute(select(Payment).where(Payment.scope_id == klass.id))
    ).scalar_one()
    assert payment.scope_type == "class"
    assert payment.status == "created"


@pytest.mark.asyncio
async def test_verify_grants_class_entitlement(client, session, cohort):
    klass = _paid_class(cohort.id)
    session.add(klass)
    await session.commit()
    order_id = client.post(f"/enrollments/classes/{klass.id}/order").json()["order_id"]
    sig = _sign(f"{order_id}|pay_CLS", SECRET)

    r = client.post(
        "/enrollments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_CLS",
            "razorpay_signature": sig,
        },
    )
    assert r.status_code == 200, r.text

    ent = (
        await session.execute(
            select(Entitlement).where(
                Entitlement.scope_type == "class", Entitlement.scope_id == klass.id
            )
        )
    ).scalar_one()
    assert ent.status == "active"
    assert ent.source == "razorpay"

    # Idempotent: a second verify doesn't create a second entitlement.
    client.post(
        "/enrollments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_CLS",
            "razorpay_signature": sig,
        },
    )
    count = (
        await session.execute(
            select(func.count()).select_from(Entitlement).where(Entitlement.scope_id == klass.id)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_free_class_not_purchasable(client, session, cohort):
    klass = _paid_class(cohort.id, access_type="free", price_single=None)
    session.add(klass)
    await session.commit()
    r = client.post(f"/enrollments/classes/{klass.id}/order")
    assert r.status_code == 409
    assert "purchasable" in r.json()["detail"]


@pytest.mark.asyncio
async def test_already_entitled_class_blocked(client, session, test_user, cohort):
    klass = _paid_class(cohort.id)
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="class",
        scope_id=klass.id,
        source="razorpay",
        status="active",
    )
    session.add_all([klass, ent])
    await session.commit()

    r = client.post(f"/enrollments/classes/{klass.id}/order")
    assert r.status_code == 409
    assert "already" in r.json()["detail"]


@pytest.mark.asyncio
async def test_ended_class_blocked(client, session, cohort):
    klass = _paid_class(cohort.id, status="ended")
    session.add(klass)
    await session.commit()
    r = client.post(f"/enrollments/classes/{klass.id}/order")
    assert r.status_code == 409
