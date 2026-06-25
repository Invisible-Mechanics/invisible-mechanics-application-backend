import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Entitlement, Payment, PaymentEvent, RecordedLecture
from app.services.razorpay import _sign

SECRET = "test-secret"


def _paid_lecture(cohort_id, **overrides) -> RecordedLecture:
    return RecordedLecture(
        id=uuid.uuid4(),
        title=overrides.pop("title", "Recorded Mechanics"),
        recorded_on=overrides.pop("recorded_on", datetime.now(UTC) - timedelta(days=1)),
        duration_min=overrides.pop("duration_min", 55),
        access_type=overrides.pop("access_type", "paid"),
        price_single=overrides.pop("price_single", Decimal("299.00")),
        cohort_id=cohort_id,
        stream_video_uid=overrides.pop("stream_video_uid", "recorded-video-uid"),
        **overrides,
    )


@pytest.mark.asyncio
async def test_create_recorded_lecture_order(client, session, cohort):
    lecture = _paid_lecture(cohort.id)
    session.add(lecture)
    await session.commit()

    r = client.post(f"/enrollments/lectures/{lecture.id}/order")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order_id"].startswith("order_FAKE")
    assert body["amount"] == 29900
    assert body["title"] == "Recorded Mechanics"

    payment = (
        await session.execute(select(Payment).where(Payment.scope_id == lecture.id))
    ).scalar_one()
    assert payment.scope_type == "recorded_lecture"
    assert payment.status == "created"

    event = (
        await session.execute(
            select(PaymentEvent).where(
                PaymentEvent.payment_id == payment.id,
                PaymentEvent.event_type == "order_created",
            )
        )
    ).scalar_one()
    assert event.source == "api"


@pytest.mark.asyncio
async def test_verify_grants_recorded_lecture_entitlement_and_playback(
    client, session, cohort
):
    lecture = _paid_lecture(cohort.id)
    session.add(lecture)
    await session.commit()
    order_id = client.post(f"/enrollments/lectures/{lecture.id}/order").json()["order_id"]
    sig = _sign(f"{order_id}|pay_VIDEO", SECRET)

    r = client.post(
        "/enrollments/verify",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_VIDEO",
            "razorpay_signature": sig,
        },
    )
    assert r.status_code == 200, r.text

    ent = (
        await session.execute(
            select(Entitlement).where(
                Entitlement.scope_type == "recorded_lecture",
                Entitlement.scope_id == lecture.id,
            )
        )
    ).scalar_one()
    assert ent.status == "active"
    assert ent.source == "razorpay"

    playback = client.get(f"/lectures/{lecture.id}/playback")
    assert playback.status_code == 200, playback.text


@pytest.mark.asyncio
async def test_recorded_lecture_purchase_history(client, session, cohort):
    lecture = _paid_lecture(cohort.id)
    session.add(lecture)
    await session.commit()
    order_id = client.post(f"/enrollments/lectures/{lecture.id}/order").json()["order_id"]

    r = client.get("/enrollments/purchases")
    assert r.status_code == 200, r.text
    purchases = r.json()
    assert purchases[0]["scope_type"] == "recorded_lecture"
    assert purchases[0]["scope_id"] == str(lecture.id)
    assert purchases[0]["razorpay_order_id"] == order_id


@pytest.mark.asyncio
async def test_verify_recorded_lecture_is_idempotent(client, session, cohort):
    lecture = _paid_lecture(cohort.id)
    session.add(lecture)
    await session.commit()
    order_id = client.post(f"/enrollments/lectures/{lecture.id}/order").json()["order_id"]
    sig = _sign(f"{order_id}|pay_VIDEO", SECRET)
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": "pay_VIDEO",
        "razorpay_signature": sig,
    }

    assert client.post("/enrollments/verify", json=payload).status_code == 200
    assert client.post("/enrollments/verify", json=payload).status_code == 200

    count = (
        await session.execute(
            select(func.count())
            .select_from(Entitlement)
            .where(
                Entitlement.scope_type == "recorded_lecture",
                Entitlement.scope_id == lecture.id,
            )
        )
    ).scalar_one()
    assert count == 1
