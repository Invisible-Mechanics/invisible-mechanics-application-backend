import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user
from app.config import get_settings
from app.db import get_db
from app.models import AuthToken, Entitlement, User
from app.routers.auth import (
    MAX_CODE_ATTEMPTS,
    MIN_RESEND_INTERVAL_SEC,
    _generate_code,
    _generate_token,
    _normalize_email,
    _normalize_phone,
    _send_login_email,
    _send_login_sms,
    _sha256,
)
from app.schemas import (
    ContactOtpRequestIn,
    ContactOtpRequestOut,
    ContactOtpVerifyIn,
    EntitlementOut,
    ProfileUpdateIn,
    ProfileUpdateOut,
    UserOut,
)
from app.services.email import EmailClient, get_email_client
from app.services.session import issue_session_jwt
from app.services.sms import SMSClient, get_sms_client

router = APIRouter(prefix="/me", tags=["me"])
PHONE_EMAIL_DOMAIN = "@phone.invisiblemechanics.com"
CONTACT_OTP_MIN_RESEND_INTERVAL_SEC = 60
CONTACT_OTP_MAX_PER_HOUR = 5


def _phone_from_placeholder_email(email: str) -> str | None:
    if not email.endswith(PHONE_EMAIL_DOMAIN):
        return None
    phone = email[: -len(PHONE_EMAIL_DOMAIN)]
    return phone if phone.isdigit() and len(phone) >= 10 else None


def _is_onboarded(user: User) -> bool:
    return bool(user.name and user.phone and user.target_exam and user.grade and user.terms_accepted_at)


def _bind_marker(user: User) -> str:
    return f"bind:{user.id}"


async def _recent_bind_token(
    db: AsyncSession,
    *,
    channel: str,
    email: str,
    phone: str | None,
    user: User,
    now: datetime,
) -> AuthToken | None:
    stmt = (
        select(AuthToken)
        .where(AuthToken.channel == channel)
        .where(AuthToken.email == email)
        .where(AuthToken.next_path == _bind_marker(user))
        .where(AuthToken.consumed_at.is_(None))
        .where(AuthToken.expires_at > now)
        .order_by(AuthToken.created_at.desc())
        .limit(1)
    )
    if phone:
        stmt = stmt.where(AuthToken.phone == phone)
    return (await db.execute(stmt)).scalar_one_or_none()


def _profile_response(user: User) -> ProfileUpdateOut:
    token, expires_at = issue_session_jwt(
        user.id,
        user.email,
        user.role,
        name=user.name,
        phone=user.phone,
        target_exam=user.target_exam,
        grade=user.grade,
        terms_accepted_at=user.terms_accepted_at,
        onboarded=_is_onboarded(user),
    )
    return ProfileUpdateOut(user=user, access_token=token, expires_at=expires_at)


@router.get("", response_model=UserOut)
async def get_me(user: User = Depends(current_user)) -> User:
    return user


@router.patch("", response_model=ProfileUpdateOut)
async def update_me(
    body: ProfileUpdateIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateOut:
    user = await db.get(User, user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    updates = body.model_dump(exclude_unset=True)
    if body.email is not None:
        new_email = str(body.email).strip().lower()
        if user.email.endswith(PHONE_EMAIL_DOMAIN):
            user.email = new_email
            user.email_verified_at = None
        elif new_email != user.email:
            raise HTTPException(status_code=409, detail="email is already set")

    for field in ("name", "target_exam", "grade"):
        if field in updates:
            setattr(user, field, updates[field])

    if body.accept_terms and user.terms_accepted_at is None:
        user.terms_accepted_at = datetime.now(UTC)
        user.consent_version = body.consent_version

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="email is already in use") from None
    await db.refresh(user)
    return _profile_response(user)


@router.post("/contact/request-otp", response_model=ContactOtpRequestOut)
async def request_contact_otp(
    body: ContactOtpRequestIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    email_client: EmailClient = Depends(get_email_client),
    sms_client: SMSClient = Depends(get_sms_client),
) -> ContactOtpRequestOut:
    user = await db.get(User, user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    settings = get_settings()
    now = datetime.now(UTC)
    is_sms = body.phone is not None
    phone = _normalize_phone(body.phone) if body.phone else None
    email = user.email if is_sms else _normalize_email(str(body.email))
    bind_phone = phone if is_sms else (user.phone or _phone_from_placeholder_email(user.email))
    channel = "sms" if is_sms else "email"

    target_value = phone if is_sms else email
    hourly_count = (
        await db.execute(
            select(func.count())
            .select_from(AuthToken)
            .where(AuthToken.channel == channel)
            .where(AuthToken.next_path == _bind_marker(user))
            .where(AuthToken.phone == target_value if is_sms else AuthToken.email == target_value)
            .where(AuthToken.created_at >= now - timedelta(hours=1))
        )
    ).scalar_one()
    if int(hourly_count) >= CONTACT_OTP_MAX_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="too many OTP requests; try again in one hour",
        )

    recent = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.channel == channel)
            .where(AuthToken.next_path == _bind_marker(user))
            .where(AuthToken.phone == target_value if is_sms else AuthToken.email == target_value)
            .order_by(AuthToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if recent is not None:
        created_at = recent.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if (now - created_at).total_seconds() < CONTACT_OTP_MIN_RESEND_INTERVAL_SEC:
            raise HTTPException(
                status_code=429,
                detail="please wait 60 seconds before requesting another OTP",
            )
    if is_sms:
        taken = (
            await db.execute(select(User.id).where(User.phone == phone, User.id != user.id))
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=409, detail="that number is already in use")
    else:
        if not user.email.endswith(PHONE_EMAIL_DOMAIN) and email != user.email:
            raise HTTPException(status_code=409, detail="email is already set")
        if user.phone is None:
            recovered_phone = _phone_from_placeholder_email(user.email)
            if recovered_phone:
                user.phone = recovered_phone
                user.phone_verified_at = user.phone_verified_at or now
        taken = (
            await db.execute(select(User.id).where(User.email == email, User.id != user.id))
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=409, detail="email is already in use")

    await db.execute(
        update(AuthToken)
        .where(AuthToken.channel == channel)
        .where(AuthToken.email == email)
        .where(AuthToken.next_path == _bind_marker(user))
        .where(AuthToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    code = _generate_code()
    token = _generate_token()
    db.add(
        AuthToken(
            channel=channel,
            email=email,
            phone=bind_phone,
            token_hash=_sha256(token),
            code_hash=_sha256(code),
            next_path=_bind_marker(user),
            expires_at=now + timedelta(minutes=settings.magic_link_ttl_min),
        )
    )
    await db.commit()

    if is_sms and phone:
        failure = await _send_login_sms(sms_client, phone=phone, code=code)
        if failure is not None:
            raise HTTPException(status_code=502, detail="could not send the code, try again")
    else:
        await _send_login_email(email_client, to=email, token=token, code=code, next_path=None)
    return ContactOtpRequestOut(dev_code=code)


@router.post("/contact/verify-otp", response_model=ProfileUpdateOut)
async def verify_contact_otp(
    body: ContactOtpVerifyIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileUpdateOut:
    user = await db.get(User, user.id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    now = datetime.now(UTC)
    is_sms = body.phone is not None
    phone = _normalize_phone(body.phone) if body.phone else None
    email = user.email if is_sms else _normalize_email(str(body.email))
    channel = "sms" if is_sms else "email"

    row = await _recent_bind_token(
        db,
        channel=channel,
        email=email,
        phone=phone,
        user=user,
        now=now,
    )
    if row is None:
        raise HTTPException(status_code=400, detail="invalid or expired code")
    if not secrets.compare_digest(row.code_hash, _sha256(body.code)):
        row.attempts += 1
        if row.attempts >= MAX_CODE_ATTEMPTS:
            row.consumed_at = now
        await db.commit()
        raise HTTPException(status_code=400, detail="invalid or expired code")

    row.consumed_at = now
    if is_sms:
        taken = (
            await db.execute(select(User.id).where(User.phone == phone, User.id != user.id))
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=409, detail="that number is already in use")
        user.phone = phone
        user.phone_verified_at = now
    else:
        if not user.email.endswith(PHONE_EMAIL_DOMAIN) and email != user.email:
            raise HTTPException(status_code=409, detail="email is already set")
        if user.phone is None:
            recovered_phone = row.phone or _phone_from_placeholder_email(user.email)
            if recovered_phone:
                user.phone = recovered_phone
                user.phone_verified_at = user.phone_verified_at or now
        taken = (
            await db.execute(select(User.id).where(User.email == email, User.id != user.id))
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=409, detail="email is already in use")
        user.email = email
        user.email_verified_at = now

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        detail = "that number is already in use" if is_sms else "email is already in use"
        raise HTTPException(status_code=409, detail=detail) from None
    await db.refresh(user)
    return _profile_response(user)


@router.get("/entitlements", response_model=list[EntitlementOut])
async def list_my_entitlements(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Entitlement]:
    now = datetime.now(UTC)
    stmt = (
        select(Entitlement)
        .where(
            Entitlement.user_id == user.id,
            Entitlement.status == "active",
            or_(Entitlement.valid_until.is_(None), Entitlement.valid_until > now),
        )
        .order_by(Entitlement.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())



