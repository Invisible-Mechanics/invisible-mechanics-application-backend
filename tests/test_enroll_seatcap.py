import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Cohort, Entitlement, Payment
from app.services.enrollment import grant_cohort_entitlement


@pytest.mark.asyncio
async def test_order_blocked_when_cohort_full(client, session):
    cohort = Cohort(
        id=uuid.uuid4(),
        title="Full cohort",
        price=Decimal("999.00"),
        seat_limit=1,
        seats_taken=1,
        status="open",
    )
    session.add(cohort)
    await session.commit()

    r = client.post(f"/enrollments/cohorts/{cohort.id}/order")
    assert r.status_code == 409
    assert "full" in r.json()["detail"]


@pytest.mark.asyncio
async def test_grant_at_cap_oversells_and_flags(session, test_user):
    cohort = Cohort(
        id=uuid.uuid4(),
        title="At cap",
        price=Decimal("999.00"),
        seat_limit=1,
        seats_taken=1,  # already full
        status="open",
    )
    payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort.id,
        razorpay_order_id="order_OVERSELL",
        amount=99900,
        currency="INR",
        status="created",
    )
    session.add_all([cohort, payment])
    await session.commit()

    await grant_cohort_entitlement(session, payment)

    await session.refresh(cohort)
    await session.refresh(payment)
    assert cohort.seats_taken == 2  # granted past the cap
    assert payment.oversold is True
    assert payment.status == "paid"

    ent_count = (
        await session.execute(
            select(func.count()).select_from(Entitlement).where(Entitlement.scope_id == cohort.id)
        )
    ).scalar_one()
    assert ent_count == 1
