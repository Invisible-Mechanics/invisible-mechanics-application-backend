import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Class
from app.services.email import FakeEmailClient, get_email_client


def _override_email(app, fake: FakeEmailClient) -> None:
    app.dependency_overrides[get_email_client] = lambda: fake


def test_cron_rejects_without_token(client):
    r = client.post("/cron/send-class-reminders")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cron_sends_reminder_for_class_in_window(client, session, test_user, cohort):
    fake = FakeEmailClient()
    _override_email(client.app, fake)

    klass = Class(
        id=uuid.uuid4(),
        title="Kinematics — Free preview",
        scheduled_start=datetime.now(timezone.utc) + timedelta(minutes=60),
        duration_min=60,
        access_type="free",
        status="scheduled",
        cohort_id=cohort.id,
        stream_live_input_uid="fake-live-input-123",
    )
    session.add(klass)
    await session.commit()

    r = client.post("/cron/send-class-reminders", headers={"X-Cron-Token": "dev"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sent"] == 1
    assert body["skipped"] == 0
    assert len(fake.sent) == 1
    assert fake.sent[0]["to"] == test_user.email

    # Re-call should dedup
    r2 = client.post("/cron/send-class-reminders", headers={"X-Cron-Token": "dev"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["sent"] == 0
    assert body2["skipped"] == 1
    assert len(fake.sent) == 1  # no second send


@pytest.mark.asyncio
async def test_cron_ignores_class_outside_window(client, session, test_user, cohort):
    fake = FakeEmailClient()
    _override_email(client.app, fake)

    klass = Class(
        id=uuid.uuid4(),
        title="Future class",
        scheduled_start=datetime.now(timezone.utc) + timedelta(hours=24),
        duration_min=60,
        access_type="free",
        status="scheduled",
        cohort_id=cohort.id,
        stream_live_input_uid="fake-live-input-456",
    )
    session.add(klass)
    await session.commit()

    r = client.post("/cron/send-class-reminders", headers={"X-Cron-Token": "dev"})
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] == 0
    assert len(fake.sent) == 0
