from datetime import datetime, timedelta, timezone


def test_admin_creates_live_class_with_fake_stream(admin_client, cohort):
    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = admin_client.post(
        "/admin/classes",
        json={
            "title": "Kinematics — 1D motion",
            "description": "Free intro session",
            "subject": "physics",
            "topic": "Kinematics",
            "scheduled_start": start,
            "duration_min": 60,
            "access_type": "free",
            "cohort_id": str(cohort.id),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "Kinematics — 1D motion"
    assert body["access_type"] == "free"
    assert body["status"] == "scheduled"
    assert body["cohort_id"] == str(cohort.id)

    # Admin can fetch RTMPS push creds for the newly-provisioned live input.
    keys = admin_client.get(f"/admin/classes/{body['id']}/stream-keys")
    assert keys.status_code == 200, keys.text
    keys_body = keys.json()
    assert keys_body["rtmps_url"].startswith("rtmps://")
    assert keys_body["rtmps_stream_key"]
    assert keys_body["live_input_uid"]


def test_admin_create_rejects_unknown_cohort(admin_client):
    import uuid

    start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = admin_client.post(
        "/admin/classes",
        json={
            "title": "Orphan",
            "scheduled_start": start,
            "duration_min": 60,
            "access_type": "free",
            "cohort_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 400
    assert "cohort" in r.json()["detail"]
