import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.models import Cohort, Payment


@pytest.mark.asyncio
async def test_create_order_for_open_cohort(client, session):
    cohort = Cohort(
        id=uuid.uuid4(),
        title="JEE Physics — Summer 2026",
        price=Decimal("1999.00"),
        seat_limit=50,
        status="open",
    )
    session.add(cohort)
    await session.commit()

    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order_id"].startswith("order_FAKE")
    assert body["amount"] == 199900  # paise
    assert body["currency"] == "INR"
    assert body["title"] == "JEE Physics — Summer 2026"
    assert "key_id" in body

    payment = (
        await session.execute(select(Payment).where(Payment.scope_id == cohort.id))
    ).scalar_one()
    assert payment.status == "created"
    assert payment.amount == 199900
    assert payment.razorpay_order_id == body["order_id"]


@pytest.mark.asyncio
async def test_order_uses_early_bird_price_before_deadline(client, session):
    from datetime import UTC, datetime, timedelta

    cohort = Cohort(
        id=uuid.uuid4(),
        title="Early bird cohort",
        price=Decimal("9999.00"),
        early_bird_price=Decimal("4999.00"),
        early_bird_deadline=datetime.now(UTC) + timedelta(days=7),
        status="open",
    )
    session.add(cohort)
    await session.commit()

    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 499900  # early-bird paise


def test_order_unknown_cohort_404(client):
    r = client.post(f"/enrollments/cohorts/{uuid.uuid4()}/order")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_order_closed_cohort_409(client, session):
    cohort = Cohort(
        id=uuid.uuid4(), title="Closed", price=Decimal("999.00"), status="closed"
    )
    session.add(cohort)
    await session.commit()
    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_order_unpriced_cohort_409(client, session):
    cohort = Cohort(id=uuid.uuid4(), title="Free-ish", status="open")  # no price
    session.add(cohort)
    await session.commit()
    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 409
    assert "purchasable" in r.json()["detail"]


@pytest.mark.asyncio
async def test_order_still_works_if_payment_audit_table_missing(client, session):
    await session.execute(text("DROP TABLE payment_events"))
    await session.commit()

    cohort = Cohort(
        id=uuid.uuid4(),
        title="Audit fallback cohort",
        price=Decimal("999.00"),
        status="open",
    )
    session.add(cohort)
    await session.commit()

    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 200, r.text

    payment = (
        await session.execute(select(Payment).where(Payment.scope_id == cohort.id))
    ).scalar_one()
    assert payment.status == "created"
