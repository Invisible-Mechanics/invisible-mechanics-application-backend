import pytest
import uuid

from app.models import MasterclassEvent


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
    assert len(rows) == 2
    assert any(row["user_email"] == "admin@example.com" for row in rows)
