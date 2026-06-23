import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import RecordedLecture, User
from app.schemas import RecordedLectureOut, RecordingPlaybackResponse
from app.services.access import can_access_recorded
from app.services.cloudflare_stream import StreamClient, get_stream_client

router = APIRouter(prefix="/lectures", tags=["recorded-lectures"])


@router.get("", response_model=list[RecordedLectureOut])
async def list_recorded_lectures(
    cohort_id: uuid.UUID | None = Query(default=None),
    target_exam: Literal["jee", "neet"] | None = Query(default=None),
    target_year: int | None = Query(default=None, ge=2026, le=2032),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[RecordedLecture]:
    stmt = select(RecordedLecture).order_by(RecordedLecture.recorded_on.desc())
    if cohort_id is not None:
        stmt = stmt.where(RecordedLecture.cohort_id == cohort_id)
    if target_exam is not None:
        stmt = stmt.where(RecordedLecture.target_exam == target_exam)
    if target_year is not None:
        stmt = stmt.where(RecordedLecture.target_year == target_year)
    stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{lecture_id}", response_model=RecordedLectureOut)
async def get_recorded_lecture(
    lecture_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> RecordedLecture:
    lecture = await db.get(RecordedLecture, lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="recorded lecture not found")
    return lecture


@router.get("/{lecture_id}/playback", response_model=RecordingPlaybackResponse)
async def get_recorded_lecture_playback(
    lecture_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
    stream: StreamClient = Depends(get_stream_client),
) -> RecordingPlaybackResponse:
    lecture = await db.get(RecordedLecture, lecture_id)
    if lecture is None:
        raise HTTPException(status_code=404, detail="recorded lecture not found")

    if not await can_access_recorded(db, user, lecture):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not entitled to this lecture",
        )

    if not lecture.stream_video_uid:
        raise HTTPException(status_code=404, detail="no video attached")

    playback = stream.sign_playback(
        video_uid=lecture.stream_video_uid,
        ttl_sec=get_settings().stream_token_ttl_sec,
    )
    return RecordingPlaybackResponse(
        hls_url=playback.hls_url,
        dash_url=playback.dash_url,
        iframe_url=playback.iframe_url,
        expires_at=playback.expires_at,
    )
