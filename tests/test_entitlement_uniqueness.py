"""The partial-unique active-entitlement index is the idempotency guard behind
the verify + webhook grant race. These tests pin that guarantee at the DB level
and prove the grant functions absorb a lost race instead of double-granting.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

import app.services.enrollment as enrollment
from app.models import Cohort, Entitlement, Payment
from app.services.enrollment import grant_cohort_entitlement


def _active_entitlement(
    user_id: uuid.UUID, scope_id: uuid.UUID, status: str = "active"
) -> Entitlement:
    return Entitlement(
        user_id=user_id,
        scope_type="cohort",
        scope_id=scope_id,
        source="razorpay",
        status=status,
    )


@pytest.mark.asyncio
async def test_duplicate_active_entitlement_is_rejected(session, test_user):
    """Two active entitlements for the same (user, scope) violate the unique index."""
    scope_id = uuid.uuid4()
    session.add(_active_entitlement(test_user.id, scope_id))
    await session.commit()

    session.add(_active_entitlement(test_user.id, scope_id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_non_active_duplicates_are_allowed(session, test_user):
    """The index is partial: only active rows are constrained. A cancelled row
    plus a fresh active row for the same scope must coexist (re-enrollment)."""
    scope_id = uuid.uuid4()
    session.add(_active_entitlement(test_user.id, scope_id, status="cancelled"))
    await session.commit()
    session.add(_active_entitlement(test_user.id, scope_id, status="cancelled"))
    await session.commit()  # two non-active rows: fine
    session.add(_active_entitlement(test_user.id, scope_id))
    await session.commit()  # one active alongside cancelled: fine

    active = (
        await session.execute(
            select(func.count())
            .select_from(Entitlement)
            .where(Entitlement.scope_id == scope_id, Entitlement.status == "active")
        )
    ).scalar_one()
    assert active == 1


@pytest.mark.asyncio
async def test_grant_absorbs_lost_race_without_overselling(session, test_user, monkeypatch):
    """Simulate the verify+webhook race: this caller's existence check ran before
    the winner committed, so it proceeds to increment the seat and insert a
    duplicate entitlement. The unique index rejects the insert; the grant must
    roll back the seat increment and finish as a clean no-op."""
    cohort = Cohort(
        id=uuid.uuid4(),
        title="Race cohort",
        price=Decimal("999.00"),
        seat_limit=50,
        seats_taken=0,
        status="open",
    )
    payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort.id,
        razorpay_order_id="order_RACELOSER",
        amount=99900,
        currency="INR",
        status="created",
    )
    # The "winner" already granted the entitlement and took the seat.
    winner = _active_entitlement(test_user.id, cohort.id)
    cohort.seats_taken = 1
    session.add_all([cohort, payment, winner])
    await session.commit()

    # Force the read-then-insert check to miss, reproducing the pre-commit race.
    async def _miss(*args, **kwargs):
        return False

    monkeypatch.setattr(enrollment, "_has_active_entitlement", _miss)

    await grant_cohort_entitlement(session, payment)

    await session.refresh(cohort)
    await session.refresh(payment)
    assert cohort.seats_taken == 1  # our increment rolled back; winner's seat stands
    assert payment.status == "paid"  # recorded paid despite the absorbed conflict

    ent_count = (
        await session.execute(
            select(func.count())
            .select_from(Entitlement)
            .where(
                Entitlement.scope_id == cohort.id,
                Entitlement.status == "active",
            )
        )
    ).scalar_one()
    assert ent_count == 1  # no duplicate entitlement


@pytest.mark.asyncio
async def test_grant_is_idempotent_on_repeat(session, test_user):
    """Calling grant twice for the same payment (verify then webhook, sequential)
    grants once, takes one seat, and writes one entitlement."""
    cohort = Cohort(
        id=uuid.uuid4(),
        title="Idempotent cohort",
        price=Decimal("999.00"),
        seat_limit=50,
        seats_taken=0,
        status="open",
    )
    payment = Payment(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort.id,
        razorpay_order_id="order_IDEMPOTENT",
        amount=99900,
        currency="INR",
        status="created",
    )
    session.add_all([cohort, payment])
    await session.commit()

    await grant_cohort_entitlement(session, payment)
    await grant_cohort_entitlement(session, payment)

    await session.refresh(cohort)
    assert cohort.seats_taken == 1

    ent_count = (
        await session.execute(
            select(func.count())
            .select_from(Entitlement)
            .where(Entitlement.scope_id == cohort.id, Entitlement.status == "active")
        )
    ).scalar_one()
    assert ent_count == 1
