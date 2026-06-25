import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.routers.me as me_router
from app.main import app
from app.models import Entitlement, User
from app.services.email import get_email_client
from app.services.sms import get_sms_client


class _FakeEmail:
    def __init__(self):
        self.sent = []

    async def send(self, *, to: str, subject: str, html: str, text: str):
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})
        return type("Result", (), {"ok": True, "id": "fake", "error": None})()


class _FakeSms:
    def __init__(self):
        self.sent = []

    async def send_otp(self, *, phone: str, code: str):
        self.sent.append({"phone": phone, "code": code})
        return type("Result", (), {"ok": True, "id": "fake", "error": None, "response_body": None})()


@pytest.mark.asyncio
async def test_me_entitlements_empty(client, test_user):
    r = client.get("/me/entitlements")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_me_entitlements_returns_active(client, session, test_user):
    cohort_id = uuid.uuid4()
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="cohort",
        scope_id=cohort_id,
        source="cohort_enrollment",
        valid_until=datetime.now(timezone.utc) + timedelta(days=30),
        status="active",
    )
    session.add(ent)
    await session.commit()

    r = client.get("/me/entitlements")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["scope_type"] == "cohort"
    assert body[0]["scope_id"] == str(cohort_id)


@pytest.mark.asyncio
async def test_me_entitlements_excludes_expired(client, session, test_user):
    ent = Entitlement(
        id=uuid.uuid4(),
        user_id=test_user.id,
        scope_type="all_access",
        scope_id=None,
        source="subscription",
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
        status="active",
    )
    session.add(ent)
    await session.commit()

    r = client.get("/me/entitlements")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_profile_update_records_student_details_and_consent(client, session, test_user):
    user_id = test_user.id
    r = client.patch(
        "/me",
        json={
            "name": "Ritank",
            "target_exam": "jee",
            "grade": "12",
            "accept_terms": True,
            "consent_version": "25 June 2026",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["user"]["name"] == "Ritank"
    assert body["user"]["target_exam"] == "jee"
    assert body["user"]["grade"] == "12"
    assert body["user"]["terms_accepted_at"] is not None

    session.expire_all()
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert user.consent_version == "25 June 2026"


@pytest.mark.asyncio
async def test_profile_consent_is_idempotent(client, session, test_user):
    user_id = test_user.id
    first = client.patch(
        "/me",
        json={
            "name": "Student",
            "target_exam": "neet",
            "grade": "11",
            "accept_terms": True,
            "consent_version": "25 June 2026",
        },
    )
    assert first.status_code == 200, first.text
    first_terms_at = first.json()["user"]["terms_accepted_at"]

    second = client.patch(
        "/me",
        json={
            "name": "Student Updated",
            "target_exam": "neet",
            "grade": "12",
            "accept_terms": True,
            "consent_version": "changed-version",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["user"]["terms_accepted_at"] == first_terms_at

    session.expire_all()
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert user.name == "Student Updated"
    assert user.grade == "12"
    assert user.consent_version == "25 June 2026"


@pytest.mark.asyncio
async def test_phone_placeholder_email_can_be_replaced(client, session, test_user):
    user_id = test_user.id
    test_user.email = "919876543210@phone.invisiblemechanics.com"
    test_user.phone = "919876543210"
    await session.commit()

    r = client.patch(
        "/me",
        json={
            "email": "real.student@example.com",
            "name": "Phone User",
            "target_exam": "jee",
            "grade": "11",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "real.student@example.com"

    session.expire_all()
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
    assert user.email == "real.student@example.com"
    assert user.phone == "919876543210"


@pytest.mark.asyncio
async def test_real_email_cannot_be_changed_from_profile(client, test_user):
    r = client.patch("/me", json={"email": "changed@example.com"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_phone_signup_binds_verified_email_without_new_account(
    client, session, test_user, monkeypatch
):
    fake_email = _FakeEmail()
    app.dependency_overrides[get_email_client] = lambda: fake_email
    monkeypatch.setattr(me_router, "_generate_code", lambda: "123456")

    user_id = test_user.id
    test_user.email = "919399039501@phone.invisiblemechanics.com"
    test_user.phone = "919399039501"
    await session.commit()

    r = client.post("/me/contact/request-otp", json={"email": "real.student@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["dev_code"] == "123456"
    assert fake_email.sent[0]["to"] == "real.student@example.com"

    v = client.post(
        "/me/contact/verify-otp",
        json={"email": "real.student@example.com", "code": "123456"},
    )
    assert v.status_code == 200, v.text
    assert v.json()["user"]["email"] == "real.student@example.com"
    assert v.json()["access_token"]

    session.expire_all()
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1
    user = users[0]
    assert user.id == user_id
    assert user.phone == "919399039501"
    assert user.email == "real.student@example.com"
    assert user.email_verified_at is not None


@pytest.mark.asyncio
async def test_email_signup_binds_verified_phone_without_new_account(
    client, session, test_user, monkeypatch
):
    fake_sms = _FakeSms()
    app.dependency_overrides[get_sms_client] = lambda: fake_sms
    monkeypatch.setattr(me_router, "_generate_code", lambda: "123456")

    user_id = test_user.id
    test_user.email = "student@example.com"
    test_user.phone = None
    await session.commit()

    r = client.post("/me/contact/request-otp", json={"phone": "9399039501"})
    assert r.status_code == 200, r.text
    assert r.json()["dev_code"] == "123456"
    assert fake_sms.sent == [{"phone": "919399039501", "code": "123456"}]

    v = client.post(
        "/me/contact/verify-otp",
        json={"phone": "9399039501", "code": "123456"},
    )
    assert v.status_code == 200, v.text
    assert v.json()["user"]["phone"] == "919399039501"
    assert v.json()["access_token"]

    session.expire_all()
    users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1
    user = users[0]
    assert user.id == user_id
    assert user.email == "student@example.com"
    assert user.phone == "919399039501"
    assert user.phone_verified_at is not None
