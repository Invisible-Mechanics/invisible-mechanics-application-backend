import uuid

import pytest

from app.models import User


@pytest.mark.asyncio
async def test_admin_can_create_admin_user(admin_client, session):
    r = admin_client.post(
        "/admin/users",
        json={
            "email": "teacher@example.com",
            "name": "Teacher",
            "phone": "919999999999",
            "role": "admin",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "teacher@example.com"
    assert body["role"] == "admin"

    user = await session.get(User, uuid.UUID(body["id"]))
    assert user is not None
    assert user.role == "admin"


def test_admin_can_search_users(admin_client):
    r = admin_client.get("/admin/users?q=admin")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(row["email"] == "admin@example.com" for row in rows)
    assert all("created_at" in row for row in rows)


@pytest.mark.asyncio
async def test_admin_can_promote_existing_user(admin_client, session, test_user):
    r = admin_client.patch(f"/admin/users/{test_user.id}/role", json={"role": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"

    await session.refresh(test_user)
    assert test_user.role == "admin"
