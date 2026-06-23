"""End-to-end HTTP walkthrough of the recorded-classes feature.

Hits a live uvicorn (default http://localhost:8000) with real Supabase-compatible
HS256 JWTs minted against the configured supabase_jwt_secret. Exercises:
  - admin CRUD (chapter, subtopic, lecture) with the Cloudflare Stream UID
  - draft hiding from the student tree
  - publish flow
  - playback gating: 403 when paid+no entitlement, 200 when free, 200 when paid
    with all_access entitlement, 404 when draft
Cleans up its own data at the end.
"""

import asyncio
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import create_async_engine

# Allow `python scripts/e2e_recorded.py` from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402

BASE_URL = "http://localhost:8000"
SETTINGS = get_settings()

ADMIN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
STUDENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def mint_token(*, sub: uuid.UUID, email: str, role: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(sub),
            "email": email,
            "aud": SETTINGS.supabase_jwt_audience,
            "iat": now,
            "exp": now + 600,
            "app_metadata": {"role": role},
        },
        SETTINGS.supabase_jwt_secret,
        algorithm="HS256",
    )


def banner(label: str) -> None:
    print(f"\n=== {label} ===")


def show(prefix: str, r: httpx.Response) -> dict | list | None:
    short = "" if r.status_code in (200, 201, 204) else f" — {r.text[:200]}"
    print(f"  {prefix}: {r.status_code}{short}")
    if r.status_code == 204 or not r.text:
        return None
    try:
        return r.json()
    except ValueError:
        return None


async def cleanup_entitlement(user_id: uuid.UUID) -> None:
    eng = create_async_engine(
        SETTINGS.database_url,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    async with eng.begin() as conn:
        await conn.execute(
            text("DELETE FROM entitlements WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    await eng.dispose()


async def grant_all_access(user_id: uuid.UUID) -> None:
    eng = create_async_engine(
        SETTINGS.database_url,
        connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    )
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO entitlements (id, user_id, scope_type, scope_id, source, "
                "valid_from, valid_until, status, created_at) "
                "VALUES (gen_random_uuid(), :uid, 'all_access', NULL, 'test_e2e', "
                "now(), :until, 'active', now())"
            ),
            {"uid": str(user_id), "until": datetime.now(UTC) + timedelta(days=1)},
        )
    await eng.dispose()


def main() -> int:
    admin_tok = mint_token(sub=ADMIN_ID, email="e2e-admin@example.com", role="admin")
    student_tok = mint_token(
        sub=STUDENT_ID, email="e2e-student@example.com", role="student"
    )
    admin_h = {"Authorization": f"Bearer {admin_tok}"}
    student_h = {"Authorization": f"Bearer {student_tok}"}

    chapter_id = subtopic_id = lecture_id = None
    failures = 0

    def assert_(label: str, ok: bool) -> None:
        nonlocal failures
        if ok:
            print(f"  [ok]   {label}")
        else:
            print(f"  [FAIL] {label}")
            failures += 1

    with httpx.Client(base_url=BASE_URL, timeout=15.0) as c:
        banner("warm-up: tree should be empty")
        tree = show("GET /recorded/tree", c.get("/recorded/tree"))
        assert_("tree starts empty", isinstance(tree, list) and tree == [])

        banner("admin creates chapter -> subtopic -> draft paid lecture")
        ch = show(
            "POST /admin/recorded/chapters",
            c.post(
                "/admin/recorded/chapters",
                headers=admin_h,
                json={"title": "E2E Mechanics", "order_index": 0},
            ),
        )
        assert_("chapter created", isinstance(ch, dict) and ch.get("title") == "E2E Mechanics")
        chapter_id = ch["id"]

        st = show(
            "POST /admin/recorded/subtopics",
            c.post(
                "/admin/recorded/subtopics",
                headers=admin_h,
                json={"chapter_id": chapter_id, "title": "Newton's laws"},
            ),
        )
        assert_("subtopic created", isinstance(st, dict))
        subtopic_id = st["id"]

        lec = show(
            "POST /admin/recorded/lectures (paid, draft)",
            c.post(
                "/admin/recorded/lectures",
                headers=admin_h,
                json={
                    "subtopic_id": subtopic_id,
                    "title": "Lecture 1: First law",
                    "cloudflare_stream_uid": "abc123deadbeef",
                    "access_type": "paid",
                    "duration_sec": 1800,
                },
            ),
        )
        assert_("lecture defaults to draft", isinstance(lec, dict) and lec.get("status") == "draft")
        assert_("admin sees stream uid", isinstance(lec, dict) and lec.get("cloudflare_stream_uid") == "abc123deadbeef")
        lecture_id = lec["id"]

        banner("draft is hidden from student tree")
        tree = show("GET /recorded/tree", c.get("/recorded/tree"))
        chapter = tree[0] if isinstance(tree, list) and tree else {}
        sub = chapter.get("subtopics", [{}])[0] if chapter else {}
        lectures = sub.get("lectures", []) if sub else []
        assert_("draft lecture absent from public tree", lectures == [])

        banner("playback on a draft -> 404")
        r = c.get(f"/recorded/lectures/{lecture_id}/playback", headers=student_h)
        show("GET .../playback", r)
        assert_("draft playback is 404", r.status_code == 404)

        banner("admin publishes the lecture")
        published = show(
            "PATCH /admin/recorded/lectures/{id} status=published",
            c.patch(
                f"/admin/recorded/lectures/{lecture_id}",
                headers=admin_h,
                json={"status": "published"},
            ),
        )
        assert_("status now published", isinstance(published, dict) and published.get("status") == "published")

        banner("student tree now includes the lecture (no stream UID leak)")
        tree = show("GET /recorded/tree", c.get("/recorded/tree"))
        chapter = tree[0] if isinstance(tree, list) and tree else {}
        sub = chapter.get("subtopics", [{}])[0] if chapter else {}
        public_lec = sub.get("lectures", [{}])[0] if sub else {}
        assert_("published lecture appears in tree", public_lec.get("id") == lecture_id)
        assert_("cloudflare_stream_uid NOT in public payload", "cloudflare_stream_uid" not in public_lec)

        banner("paid lecture, no entitlement -> 403")
        r = c.get(f"/recorded/lectures/{lecture_id}/playback", headers=student_h)
        show("GET .../playback", r)
        assert_("no entitlement -> 403", r.status_code == 403)

        banner("flip access_type=free -> student can stream")
        show(
            "PATCH access_type=free",
            c.patch(
                f"/admin/recorded/lectures/{lecture_id}",
                headers=admin_h,
                json={"access_type": "free"},
            ),
        )
        r = c.get(f"/recorded/lectures/{lecture_id}/playback", headers=student_h)
        body = show("GET .../playback", r)
        assert_("free playback -> 200", r.status_code == 200)
        assert_(
            "fake stream URL returned (since no CF creds)",
            isinstance(body, dict)
            and "fake-stream.local" in (body.get("iframe_url") or ""),
        )

        banner("flip back to paid; grant all_access entitlement; student can stream")
        show(
            "PATCH access_type=paid",
            c.patch(
                f"/admin/recorded/lectures/{lecture_id}",
                headers=admin_h,
                json={"access_type": "paid"},
            ),
        )
        asyncio.run(grant_all_access(STUDENT_ID))
        r = c.get(f"/recorded/lectures/{lecture_id}/playback", headers=student_h)
        body = show("GET .../playback", r)
        assert_("paid + all_access -> 200", r.status_code == 200)
        assert_(
            "playback includes hls + iframe + expiry",
            isinstance(body, dict)
            and all(k in body for k in ("hls_url", "iframe_url", "expires_at")),
        )

        banner("teardown: delete chapter (cascades), revoke entitlement")
        r = c.delete(f"/admin/recorded/chapters/{chapter_id}", headers=admin_h)
        show("DELETE /admin/recorded/chapters/{id}", r)
        assert_("chapter delete -> 204", r.status_code == 204)
        asyncio.run(cleanup_entitlement(STUDENT_ID))

        banner("post-teardown tree is empty again")
        tree = show("GET /recorded/tree", c.get("/recorded/tree"))
        assert_("tree empty after cleanup", tree == [])

    print(f"\n{'PASSED' if failures == 0 else f'FAILED ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
