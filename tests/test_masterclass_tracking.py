import pytest
import uuid

from app.models import MasterclassEvent
import app.services.enrollment_notifications as notification_service


class _FakeEnrollmentEmail:
    def __init__(self):
        self.sent = []

    async def send(self, *, to, subject, html, text, attachments=None):
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "html": html,
                "text": text,
                "attachments": attachments or [],
            }
        )
        return type("Result", (), {"ok": True, "id": "fake", "error": None})()


class _FakeEnrollmentSMS:
    def __init__(self):
        self.sent = []

    async def send_enrollment(self, *, phone, program_title, program_details):
        self.sent.append(
            {
                "phone": phone,
                "program_title": program_title,
                "program_details": program_details,
            }
        )
        return type("Result", (), {"ok": True, "error": None, "response_body": {}})()


def test_public_enroll_click_is_tracked(client):
    r = client.post(
        "/masterclass/events",
        json={
            "visitor_id": "visitor-123456",
            "event_type": "enroll_now_clicked",
            "source": "ad_modal",
            "path": "/",
        },
        headers={"User-Agent": "pytest"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["event_type"] == "enroll_now_clicked"
    assert body["visitor_id"] == "visitor-123456"
    assert body["user_id"] is None
    assert body["user_agent"] == "pytest"


@pytest.mark.asyncio
async def test_registration_completion_is_tied_to_user(client, session, test_user):
    r = client.post(
        "/masterclass/events/registration-completed",
        json={
            "visitor_id": "visitor-abcdef",
            "event_type": "registration_completed",
            "source": "onboarding",
            "path": "/onboarding",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["event_type"] == "registration_completed"
    assert body["user_id"] == str(test_user.id)

    event = await session.get(MasterclassEvent, uuid.UUID(body["id"]))
    assert event is not None
    assert event.user_id == test_user.id


@pytest.mark.asyncio
async def test_existing_user_masterclass_confirmation_is_idempotent(
    client, session, test_user, monkeypatch
):
    test_user.name = "Existing Student"
    test_user.phone = "919876543210"
    await session.commit()
    fake_email = _FakeEnrollmentEmail()
    fake_sms = _FakeEnrollmentSMS()
    monkeypatch.setattr(notification_service, "get_email_client", lambda: fake_email)
    monkeypatch.setattr(notification_service, "get_sms_client", lambda: fake_sms)

    payload = {
        "visitor_id": "visitor-existing",
        "event_type": "enrollment_confirmed",
        "source": "masterclass_page",
        "path": "/masterclass",
    }
    first = client.post("/masterclass/events/enrollment-confirmed", json=payload)
    second = client.post("/masterclass/events/enrollment-confirmed", json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]

    rows = (
        await session.execute(
            MasterclassEvent.__table__.select().where(
                MasterclassEvent.user_id == test_user.id,
                MasterclassEvent.event_type == "enrollment_confirmed",
            )
        )
    ).all()
    assert len(rows) == 1
    assert len(fake_email.sent) == 1
    assert fake_email.sent[0]["to"] == "student@example.com"
    assert "Masterclass" in fake_email.sent[0]["subject"]
    assert len(fake_sms.sent) == 1
    assert fake_sms.sent[0]["phone"] == "919876543210"
    assert fake_sms.sent[0]["program_title"] == "Masterclass"


def test_admin_can_read_masterclass_summary_and_events(admin_client):
    admin_client.post(
        "/masterclass/events",
        json={
            "visitor_id": "visitor-click",
            "event_type": "enroll_now_clicked",
            "source": "ad_modal",
            "path": "/",
        },
    )
    admin_client.post(
        "/masterclass/events/registration-completed",
        json={
            "visitor_id": "visitor-click",
            "event_type": "registration_completed",
            "source": "onboarding",
            "path": "/onboarding",
        },
    )

    summary = admin_client.get("/admin/masterclass/summary")
    assert summary.status_code == 200, summary.text
    assert summary.json()["enroll_now_clicked"] == 1
    assert summary.json()["registration_completed"] == 1

    events = admin_client.get("/admin/masterclass/events")
    assert events.status_code == 200, events.text
    rows = events.json()
    assert len(rows) == 3
    assert any(row["user_email"] == "admin@example.com" for row in rows)
    assert any(row["event_type"] == "enrollment_confirmed" for row in rows)
