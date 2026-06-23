import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import Class, User
from app.schemas import ClassOut, JoinResponse, RecordingPlaybackResponse
from app.services.access import can_access
from app.services.cloudflare_stream import StreamClient, get_stream_client

router = APIRouter(prefix="/classes", tags=["classes"])


@router.get("", response_model=list[ClassOut])
async def list_classes(
    upcoming_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> list[Class]:
    stmt = select(Class).order_by(Class.scheduled_start.asc())
    if upcoming_only:
        stmt = stmt.where(Class.scheduled_start >= datetime.now(UTC))
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{class_id}", response_model=ClassOut)
async def get_class(class_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Class:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")
    return klass


@router.post("/{class_id}/join", response_model=JoinResponse)
async def join_class(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    stream: StreamClient = Depends(get_stream_client),
) -> JoinResponse:
    """Issue a short-lived signed HLS URL for the class's live broadcast.

    The Cloudflare Stream JWT signs against the live input UID and the same
    playback URL pattern as a Stream video works.
    """
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")

    if not await can_access(db, user, klass):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not entitled to this lecture",
        )

    if not klass.stream_live_input_uid:
        raise HTTPException(status_code=409, detail="lecture has no live input yet")

    playback = stream.sign_playback(
        video_uid=klass.stream_live_input_uid,
        ttl_sec=get_settings().stream_token_ttl_sec,
    )
    return JoinResponse(
        hls_url=playback.hls_url,
        dash_url=playback.dash_url,
        iframe_url=playback.iframe_url,
        expires_at=playback.expires_at,
    )


@router.get("/{class_id}/recording", response_model=RecordingPlaybackResponse)
async def get_recording_playback(
    class_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    stream: StreamClient = Depends(get_stream_client),
) -> RecordingPlaybackResponse:
    klass = await db.get(Class, class_id)
    if klass is None:
        raise HTTPException(status_code=404, detail="lecture not found")

    if not await can_access(db, user, klass):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not entitled to this recording",
        )

    if not klass.stream_video_uid:
        raise HTTPException(status_code=404, detail="no recording available")

    playback = stream.sign_playback(
        video_uid=klass.stream_video_uid,
        ttl_sec=get_settings().stream_token_ttl_sec,
    )
    return RecordingPlaybackResponse(
        hls_url=playback.hls_url,
        dash_url=playback.dash_url,
        iframe_url=playback.iframe_url,
        expires_at=playback.expires_at,
    )
