"""Cron endpoints, protected by a shared secret in the X-Cron-Token header.

In dev: curl with X-Cron-Token: dev.
In prod: Vercel Cron → small Next.js route forwarder → here.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Class, EmailLog, Entitlement, User
from app.services.email import EmailClient, get_email_client, render_template
from app.services.stream_live import StreamLiveClient, get_stream_live_client
from app.services.stream_webhook import apply_live_input_event

router = APIRouter(prefix="/cron", tags=["cron"])

REMINDER_KIND = "class_reminder_1h"


async def require_cron_token(x_cron_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not x_cron_token or x_cron_token != settings.cron_shared_secret:
        raise HTTPException(status_code=401, detail="invalid cron token")


@router.post("/send-class-reminders", dependencies=[Depends(require_cron_token)])
async def send_class_reminders(
    db: AsyncSession = Depends(get_db),
    email: EmailClient = Depends(get_email_client),
) -> dict[str, object]:
    """Send 1-hour-before reminders for upcoming classes.

    Window: scheduled_start ∈ [now+55min, now+65min]. The 10-minute window
    means a cron firing every ~15 minutes catches each class at least once,
    and the email_log dedup handles overlap.
    """
    now = datetime.now(UTC)
    window_start = now + timedelta(minutes=55)
    window_end = now + timedelta(minutes=65)

    classes = (
        await db.execute(
            select(Class).where(
                Class.scheduled_start >= window_start,
                Class.scheduled_start <= window_end,
                Class.status == "scheduled",
            )
        )
    ).scalars().all()

    sent = 0
    skipped = 0
    failed = 0

    for klass in classes:
        recipients = await _recipients_for_class(db, klass)
        for user in recipients:
            already = (
                await db.execute(
                    select(EmailLog.id).where(
                        EmailLog.user_id == user.id,
                        EmailLog.class_id == klass.id,
                        EmailLog.kind == REMINDER_KIND,
                    )
                )
            ).scalar_one_or_none()
            if already:
                skipped += 1
                continue

            # Students join the live broadcast inside the web app (HLS player
            # on the class detail page), so the reminder links there rather
            # than handing out a raw stream URL.
            join_url = f"{get_settings().web_origin.rstrip('/')}/classes/{klass.id}"
            html = render_template(
                "class_reminder.html",
                title=klass.title,
                start_local=klass.scheduled_start.strftime("%a %d %b · %H:%M %Z"),
                duration_min=klass.duration_min,
                join_url=join_url,
            )
            text = render_template(
                "class_reminder.txt",
                title=klass.title,
                start_local=klass.scheduled_start.strftime("%a %d %b · %H:%M %Z"),
                duration_min=klass.duration_min,
                join_url=join_url,
            )
            result = await email.send(
                to=user.email,
                subject=f"Starts in 1 hour: {klass.title}",
                html=html,
                text=text,
            )
            if not result.ok:
                failed += 1
                continue

            db.add(
                EmailLog(user_id=user.id, class_id=klass.id, kind=REMINDER_KIND)
            )
            await db.commit()
            sent += 1

    return {"window_start": window_start, "window_end": window_end, "sent": sent, "skipped": skipped, "failed": failed}


@router.post("/sync-class-statuses", dependencies=[Depends(require_cron_token)])
async def sync_class_statuses(
    db: AsyncSession = Depends(get_db),
    stream: StreamLiveClient = Depends(get_stream_live_client),
) -> dict[str, object]:
    """Fallback poller: reconcile live-input state for classes near their window.

    Same state machine as `POST /stream/webhook`, driven by `get_status()`
    instead of an incoming event. Catches dropped/delayed webhooks and works
    even when webhook ingestion is disabled. Idempotent — running it twice in
    a row is a no-op once everything has settled.

    Window: scheduled_start ∈ [now-2h, now+2h]. Two hours before catches
    early-starting instructors; two hours after gives recordings time to
    finalize. Anything stale past that should be hand-fixed by an admin.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=2)
    window_end = now + timedelta(hours=2)

    classes = (
        await db.execute(
            select(Class).where(
                Class.scheduled_start >= window_start,
                Class.scheduled_start <= window_end,
                Class.status.in_(("scheduled", "live")),
                Class.stream_live_input_uid.is_not(None),
            )
        )
    ).scalars().all()

    checked = 0
    transitioned = 0
    attached = 0
    errors = 0

    for klass in classes:
        checked += 1
        try:
            status = await stream.get_status(klass.stream_live_input_uid)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            errors += 1
            continue

        if status.connected:
            result = await apply_live_input_event(
                db, klass, "connected", stream_client=stream, now=now
            )
        else:
            # Two passes when disconnected: try the ending transition first
            # (which auto-attaches if past the grace window), and if the
            # broadcast hasn't started yet (still "scheduled") the disconnect
            # is a no-op — which is correct.
            result = await apply_live_input_event(
                db, klass, "disconnected", stream_client=stream, now=now
            )
            # Catch up a recording for an already-ended class whose webhook
            # we missed.
            if (
                not result.recording_attached
                and klass.status == "ended"
                and not klass.stream_video_uid
                and status.recording_video_uids
            ):
                video_uid = status.recording_video_uids[0]
                result = await apply_live_input_event(
                    db,
                    klass,
                    "recording_ready",
                    stream_client=stream,
                    video_uid=video_uid,
                    now=now,
                )

        if result.status_changed:
            transitioned += 1
        if result.recording_attached:
            attached += 1

    return {
        "checked": checked,
        "transitioned": transitioned,
        "attached": attached,
        "errors": errors,
    }


async def _recipients_for_class(db: AsyncSession, klass: Class) -> list[User]:
    """Phase 0 recipient logic:
    - Free class → every user (we'll narrow this once we have an opt-in concept)
    - Paid class → users with an active entitlement covering this class
    """
    if klass.access_type == "free":
        return list((await db.execute(select(User))).scalars().all())

    now = datetime.now(UTC)
    scope_clauses = [
        Entitlement.scope_type == "all_access",
        (Entitlement.scope_type == "class") & (Entitlement.scope_id == klass.id),
    ]
    if klass.cohort_id is not None:
        scope_clauses.append(
            (Entitlement.scope_type == "cohort") & (Entitlement.scope_id == klass.cohort_id)
        )

    stmt = (
        select(User)
        .join(Entitlement, Entitlement.user_id == User.id)
        .where(
            Entitlement.status == "active",
            or_(Entitlement.valid_until.is_(None), Entitlement.valid_until > now),
            or_(*scope_clauses),
        )
        .distinct()
    )
    return list((await db.execute(stmt)).scalars().all())
