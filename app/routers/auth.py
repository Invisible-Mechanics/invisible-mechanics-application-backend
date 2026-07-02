"""Magic-link + 6-digit-code login.

Flow:
  1. POST /auth/request {email, next?} OR {phone, next?}
     -> upsert user; mint a random URL token + a 6-digit code; store
        SHA-256 hashes in auth_tokens; email or SMS the challenge.
  2a. POST /auth/verify {email, code} OR {phone, code}
  2b. POST /auth/verify-link {token}             (same-device link click)
     -> verify hash, mark consumed, issue our HS256 session JWT.
"""

import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import AuthToken, User
from app.schemas import (
    LoginRequestIn,
    LoginRequestOut,
    LoginVerifyCodeIn,
    LoginVerifyLinkIn,
    LoginVerifyOut,
)
from app.services.email import EmailClient, get_email_client, render_template
from app.services.session import issue_session_jwt
from app.services.sms import SMSClient, get_sms_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# How often a single email can request a new code. Stops accidental floods
# without needing a separate rate-limit store; auth_tokens itself is the ledger.
MIN_RESEND_INTERVAL_SEC = 30
# Max wrong-code submissions per outstanding token before it's burned.
MAX_CODE_ATTEMPTS = 5
MAX_REQUESTS_PER_HOUR = 10


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    # secrets.randbelow keeps it uniform; zero-pad to 6 digits.
    return f"{secrets.randbelow(1_000_000):06d}"


def _generate_token() -> str:
    # 32 bytes -> 43-char urlsafe string, plenty of entropy for one-shot use.
    return secrets.token_urlsafe(32)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = f"91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    raise HTTPException(status_code=422, detail="enter a valid Indian mobile number")


def _phone_email(phone: str) -> str:
    return f"{phone}@phone.invisiblemechanics.com"


def _safe_next(value: str | None) -> str | None:
    """Only accept relative paths under /. Reject absolute URLs and protocol-relative."""
    if not value:
        return None
    v = value.strip()
    if not v.startswith("/") or v.startswith("//"):
        return None
    return v[:500]


async def _send_login_email(
    email_client: EmailClient,
    *,
    to: str,
    token: str,
    code: str,
    next_path: str | None,
) -> bool:
    settings = get_settings()
    qs = f"?t={quote(token)}"
    if next_path:
        qs += f"&next={quote(next_path)}"
    magic_link = f"{settings.web_origin}/auth/callback{qs}"
    ctx = {
        "magic_link": magic_link,
        "code": code,
        "expires_min": settings.magic_link_ttl_min,
    }
    html = render_template("login_link.html", **ctx)
    text = render_template("login_link.txt", **ctx)
    result = await email_client.send(
        to=to,
        subject="Your Invisible Mechanics sign-in link",
        html=html,
        text=text,
    )
    if not result.ok:
        logger.warning("login email send failed to=%s error=%s", to, result.error)
        return False
    return True


async def _send_login_sms(
    sms_client: SMSClient,
    *,
    phone: str,
    code: str,
) -> JSONResponse | None:
    result = await sms_client.send_otp(phone=phone, code=code)
    if not result.ok:
        logger.warning("login sms send failed phone_tail=%s error=%s", phone[-4:], result.error)
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "message": "OTP SMS failed",
                "msg91": result.response_body or {"message": result.error or "MSG91 error"},
            },
        )
    return None


@router.post("/request", response_model=LoginRequestOut)
async def request_login(
    body: LoginRequestIn,
    db: AsyncSession = Depends(get_db),
    email_client: EmailClient = Depends(get_email_client),
    sms_client: SMSClient = Depends(get_sms_client),
) -> LoginRequestOut | JSONResponse:
    settings = get_settings()
    is_sms = body.phone is not None
    phone = _normalize_phone(body.phone) if body.phone else None
    email = _phone_email(phone) if phone else _normalize_email(str(body.email))
    next_path = _safe_next(body.next)
    now = datetime.now(UTC)

    hourly_count = (
        await db.execute(
            select(AuthToken.id)
            .where(AuthToken.phone == phone if is_sms else AuthToken.email == email)
            .where(AuthToken.channel == ("sms" if is_sms else "email"))
            .where(AuthToken.created_at >= now - timedelta(hours=1))
        )
    ).scalars().all()
    if len(hourly_count) >= MAX_REQUESTS_PER_HOUR:
        raise HTTPException(status_code=429, detail="too many OTP requests; try again later")

    # Rate limit: deny if there's an unconsumed, unexpired token created in the
    # last MIN_RESEND_INTERVAL_SEC. Always return ok=True externally so we don't
    # leak which addresses are registered or rate-limited — we just skip sending.
    recent = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.phone == phone if is_sms else AuthToken.email == email)
            .where(AuthToken.channel == ("sms" if is_sms else "email"))
            .where(AuthToken.consumed_at.is_(None))
            .where(AuthToken.expires_at > now)
            .order_by(AuthToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is not None:
        # SQLite (used in tests) returns naive datetimes; normalize to UTC so
        # the subtraction works regardless of DB driver.
        created_at = recent.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if (now - created_at).total_seconds() < MIN_RESEND_INTERVAL_SEC:
            return LoginRequestOut()

    # Upsert the user by the identifier used for this login request.
    user_query = (
        select(User).where(User.phone == phone)
        if is_sms
        else select(User).where(User.email == email)
    )
    user = (await db.execute(user_query)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            phone=phone,
            role="student",
            source="sms_otp" if is_sms else "magic_link",
        )
        db.add(user)
        await db.flush()
    elif is_sms and user.phone != phone:
        user.phone = phone

    # Invalidate any prior unconsumed tokens for this email so the most recent
    # request is the only valid one. Cheaper than per-row deletes and keeps the
    # log around for audit.
    await db.execute(
        update(AuthToken)
        .where(AuthToken.phone == phone if is_sms else AuthToken.email == email)
        .where(AuthToken.channel == ("sms" if is_sms else "email"))
        .where(AuthToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    code = _generate_code()
    token = _generate_token()
    row = AuthToken(
        channel="sms" if is_sms else "email",
        email=email,
        phone=phone,
        token_hash=_sha256(token),
        code_hash=_sha256(code),
        next_path=next_path,
        expires_at=now + timedelta(minutes=settings.magic_link_ttl_min),
    )
    db.add(row)
    await db.commit()

    if is_sms:
        failure = await _send_login_sms(sms_client, phone=phone, code=code)
        if failure is not None:
            row.consumed_at = datetime.now(UTC)
            await db.commit()
            return failure
    else:
        sent = await _send_login_email(
            email_client,
            to=email,
            token=token,
            code=code,
            next_path=next_path,
        )
        if not sent:
            row.consumed_at = datetime.now(UTC)
            await db.commit()
            raise HTTPException(status_code=502, detail="could not send the code, try again")
    return LoginRequestOut(dev_code=code if settings.expose_dev_codes else None)


async def _consume_and_issue(
    db: AsyncSession,
    row: AuthToken,
) -> LoginVerifyOut:
    now = datetime.now(UTC)
    row.consumed_at = now
    await db.flush()

    user = None
    if row.phone:
        user = (
            await db.execute(select(User).where(User.phone == row.phone))
        ).scalar_one_or_none()
    if user is None:
        user = (
            await db.execute(select(User).where(User.email == row.email))
        ).scalar_one_or_none()
    if user is None:
        # Shouldn't happen — /auth/request upserts the user — but be defensive.
        user = User(
            email=row.email,
            phone=row.phone,
            role="student",
            source="sms_otp" if row.phone else "magic_link",
        )
        db.add(user)
        await db.flush()
    elif row.phone and user.phone is None:
        user.phone = row.phone

    token, expires_at = issue_session_jwt(
        user.id,
        user.email,
        user.role,
        name=user.name,
        phone=user.phone,
        target_exam=user.target_exam,
        grade=user.grade,
        terms_accepted_at=user.terms_accepted_at,
        onboarded=bool(user.name and user.phone and user.target_exam and user.grade and user.terms_accepted_at),
    )
    await db.commit()
    return LoginVerifyOut(
        access_token=token,
        expires_at=expires_at,
        user=user,
        next=row.next_path,
    )


@router.post("/verify", response_model=LoginVerifyOut)
async def verify_code(
    body: LoginVerifyCodeIn,
    db: AsyncSession = Depends(get_db),
) -> LoginVerifyOut:
    is_sms = body.phone is not None
    phone = _normalize_phone(body.phone) if body.phone else None
    email = _phone_email(phone) if phone else _normalize_email(str(body.email))
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.phone == phone if is_sms else AuthToken.email == email)
            .where(AuthToken.channel == ("sms" if is_sms else "email"))
            .where(AuthToken.consumed_at.is_(None))
            .where(AuthToken.expires_at > now)
            .order_by(AuthToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="invalid or expired code")

    # Constant-time compare on the hashes so wrong codes don't leak timing.
    if not secrets.compare_digest(row.code_hash, _sha256(body.code)):
        row.attempts += 1
        if row.attempts >= MAX_CODE_ATTEMPTS:
            row.consumed_at = now
        await db.commit()
        raise HTTPException(status_code=400, detail="invalid or expired code")

    return await _consume_and_issue(db, row)


@router.post("/verify-link", response_model=LoginVerifyOut)
async def verify_link(
    body: LoginVerifyLinkIn,
    db: AsyncSession = Depends(get_db),
) -> LoginVerifyOut:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.token_hash == _sha256(body.token))
            .where(AuthToken.consumed_at.is_(None))
            .where(AuthToken.expires_at > now)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=400, detail="invalid or expired link")
    return await _consume_and_issue(db, row)
