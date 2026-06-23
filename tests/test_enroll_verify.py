import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Cohort, Entitlement, Payment
from app.services.razorpay import _sign

SECRET = "test-secret"  # matches conftest RAZORPAY_KEY_SECRET


async def _make_order(client, session, **cohort_kwargs) -> str:
    cohort = Cohort(
        id=uuid.uuid4(),
        title=cohort_kwargs.pop("title", "Cohort"),
        price=Decimal("1999.00"),
        seat_limit=cohort_kwargs.pop("seat_limit", 50),
        status="open",
        **cohort_kwargs,
    )
    session.add(cohort)
    await session.commit()
    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 200, r.text
    return r.json()["order_id"], cohort.id


@pytest.mark.asyncio
async def test_verify_grants_entitlement_and_increments_seats(client, session):
    order_id, cohort_id = await _make_order(client, session)
    sig = _sign(f"{order_id}|pay_TEST", SECRET)

    r = client.post(
        "/enrollments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_TEST",
            "razorpay_signature": sig,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "enrolled"

    ent_count = (
        await session.execute(
            select(func.count())
            .select_from(Entitlement)
            .where(Entitlement.scope_type == "cohort", Entitlement.scope_id == cohort_id)
        )
    ).scalar_one()
    assert ent_count == 1

    cohort = await session.get(Cohort, cohort_id)
    await session.refresh(cohort)
    assert cohort.seats_taken == 1

    payment = (
        await session.execute(select(Payment).where(Payment.razorpay_order_id == order_id))
    ).scalar_one()
    await session.refresh(payment)
    assert payment.status == "paid"
    assert payment.razorpay_payment_id == "pay_TEST"


@pytest.mark.asyncio
async def test_verify_is_idempotent(client, session):
    order_id, cohort_id = await _make_order(client, session)
    sig = _sign(f"{order_id}|pay_TEST", SECRET)
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": "pay_TEST",
        "razorpay_signature": sig,
    }
    assert client.post("/enrollments/verify", json=payload).status_code == 200
    assert client.post("/enrollments/verify", json=payload).status_code == 200

    ent_count = (
        await session.execute(
            select(func.count())
            .select_from(Entitlement)
            .where(Entitlement.scope_id == cohort_id)
        )
    ).scalar_one()
    assert ent_count == 1  # not double-granted

    cohort = await session.get(Cohort, cohort_id)
    await session.refresh(cohort)
    assert cohort.seats_taken == 1  # not double-counted


@pytest.mark.asyncio
async def test_verify_bad_signature_400(client, session):
    order_id, _ = await _make_order(client, session)
    r = client.post(
        "/enrollments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_TEST",
            "razorpay_signature": "deadbeef",
        },
    )
    assert r.status_code == 400
