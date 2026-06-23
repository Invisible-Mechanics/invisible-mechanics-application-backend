"""Session JWT verification.

The web app sets a cookie with our own HS256 JWT after /auth/verify. API
clients pass it back as `Authorization: Bearer <jwt>`. We decode + look up
the user; we do NOT mint users here — that happens at /auth/request time.
"""

import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.services.session import SessionError, decode_session_jwt


class AuthError(HTTPException):
    def __init__(self, detail: str = "invalid auth"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_session_jwt(token)
    except SessionError as e:
        raise AuthError(str(e)) from e

    sub = claims.get("sub")
    if not sub:
        raise AuthError("token missing sub")
    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError) as e:
        raise AuthError("token sub is not a uuid") from e

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise AuthError("user not found")
    return user


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
