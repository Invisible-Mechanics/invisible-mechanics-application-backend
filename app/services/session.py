"""Session JWT issue + decode.

The same APP_JWT_SECRET is also configured on the Next.js side so its
middleware can verify cookies without a round-trip to FastAPI.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings

ALGORITHM = "HS256"


class SessionError(Exception):
    pass


def issue_session_jwt(user_id: uuid.UUID, email: str, role: str) -> tuple[str, datetime]:
    settings = get_settings()
    if not settings.app_jwt_secret:
        raise SessionError("APP_JWT_SECRET not configured")
    now = datetime.now(UTC)
    exp = now + timedelta(days=settings.session_ttl_days)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.app_jwt_secret, algorithm=ALGORITHM), exp


def decode_session_jwt(token: str) -> dict:
    settings = get_settings()
    if not settings.app_jwt_secret:
        raise SessionError("APP_JWT_SECRET not configured")
    try:
        return jwt.decode(token, settings.app_jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as e:
        raise SessionError(f"invalid session token: {e}") from e
