"""Admin CRUD for standalone recorded lectures (separate from Class)."""

import uuid
from datetime import UTC, datetime, timedelta


def _payload(cohort_id, **overrides) -> dict:
    base = {
        "title": "Rotational dynamics primer",
        "description": "Quick recap before the live class.",
        "subject": "physics",
        "topic": "Rotation",
        "recorded_on": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        "duration_min": 45,
        "access_type": "free",
        "cohort_id": str(cohort_id),
        "stream_video_uid": "abcdef0123456789",
        "thumbnail_url": "https://cdn.example/test.jpg",
        "target_exam": "jee",
        "target_year": 2027,
    }
    base.update(overrides)
    return base


def test_admin_creates_recorded_lecture(admin_client, cohort):
    r = admin_client.post("/admin/recorded-lectures", json=_payload(cohort.id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Rotational dynamics primer"
    assert body["access_type"] == "free"
    assert body["stream_video_uid"] == "abcdef0123456789"
    assert body["cohort_id"] == str(cohort.id)
    assert body["target_exam"] == "jee"
    assert body["target_year"] == 2027


def test_admin_create_rejects_unknown_cohort(admin_client):
    r = admin_client.post(
        "/admin/recorded-lectures",
        json=_payload(uuid.uuid4()),
    )
    assert r.status_code == 400
    assert "cohort" in r.json()["detail"]


def test_admin_create_requires_stream_video_uid(admin_client, cohort):
    payload = _payload(cohort.id)
    del payload["stream_video_uid"]
    r = admin_client.post("/admin/recorded-lectures", json=payload)
    assert r.status_code == 422


def test_admin_update_recorded_lecture(admin_client, cohort):
    created = admin_client.post("/admin/recorded-lectures", json=_payload(cohort.id)).json()
    r = admin_client.patch(
        f"/admin/recorded-lectures/{created['id']}",
        json={"title": "Renamed", "duration_min": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Renamed"
    assert body["duration_min"] == 30


def test_admin_update_rejects_unknown_cohort(admin_client, cohort):
    created = admin_client.post("/admin/recorded-lectures", json=_payload(cohort.id)).json()
    r = admin_client.patch(
        f"/admin/recorded-lectures/{created['id']}",
        json={"cohort_id": str(uuid.uuid4())},
    )
    assert r.status_code == 400


def test_admin_delete_recorded_lecture(admin_client, cohort):
    created = admin_client.post("/admin/recorded-lectures", json=_payload(cohort.id)).json()
    assert (
        admin_client.delete(f"/admin/recorded-lectures/{created['id']}").status_code == 204
    )
    assert admin_client.get(f"/lectures/{created['id']}").status_code == 404


def test_admin_lists_recorded_lectures_recorded_on_desc(admin_client, cohort):
    older = admin_client.post(
        "/admin/recorded-lectures",
        json=_payload(
            cohort.id,
            title="Older",
            recorded_on=(datetime.now(UTC) - timedelta(days=10)).isoformat(),
        ),
    ).json()
    newer = admin_client.post(
        "/admin/recorded-lectures",
        json=_payload(
            cohort.id,
            title="Newer",
            recorded_on=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        ),
    ).json()
    r = admin_client.get("/admin/recorded-lectures")
    assert r.status_code == 200
    titles = [row["title"] for row in r.json()]
    assert titles.index("Newer") < titles.index("Older")
    assert {newer["id"], older["id"]}.issubset({row["id"] for row in r.json()})
