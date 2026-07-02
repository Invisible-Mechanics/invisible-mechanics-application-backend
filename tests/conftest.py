"""Test fixtures: SQLite-backed in-memory DB and a TestClient with auth stubbed.

The real app verifies our HS256 session JWTs; most tests bypass that with a
dependency override that injects a fixed test user. The auth-flow tests in
test_auth_login.py exercise the real verification path.
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("APP_JWT_SECRET", "test-secret")
os.environ.setdefault("EXPOSE_DEV_CODES", "true")
# Env vars take precedence over .env, so these override the real Razorpay keys
# during tests, giving deterministic signatures. Key id stays empty -> Fake client.
os.environ.setdefault("RAZORPAY_KEY_ID", "")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "test-secret")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "test-webhook-secret")
# Force the fake Cloudflare / Stream clients regardless of the developer's
# real .env, so tests don't hit the live API.
os.environ["CLOUDFLARE_API_TOKEN"] = ""
os.environ["CLOUDFLARE_ACCOUNT_ID"] = ""
os.environ["CLOUDFLARE_STREAM_CUSTOMER_CODE"] = ""
os.environ["CLOUDFLARE_STREAM_SIGNING_KEY_ID"] = ""
os.environ["CLOUDFLARE_STREAM_SIGNING_KEY_PEM"] = ""
# Pinned so signature-verification tests have a deterministic secret. The
# real LiveStreamLiveClient stays disabled because the API token above is "".
os.environ["CLOUDFLARE_STREAM_WEBHOOK_SECRET"] = "test-stream-webhook-secret"

from app import db as db_module  # noqa: E402
from app.auth import current_user, require_admin  # noqa: E402
from app.db import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Cohort, User  # noqa: E402
from app.services.razorpay import FakeRazorpayClient, get_razorpay_client  # noqa: E402


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        yield s


@pytest_asyncio.fixture
async def test_user(session: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email="student@example.com", role="student")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def admin_user(session: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email="admin@example.com", role="admin")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture
async def cohort(session: AsyncSession) -> Cohort:
    """A default cohort for tests that just need a parent for a class.

    Classes now require a cohort_id; tests that don't care about cohort
    semantics use this default. Tests that exercise cohort logic create
    their own cohorts.
    """
    c = Cohort(id=uuid.uuid4(), title="Test cohort")
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


@pytest.fixture
def client(engine, session, test_user) -> TestClient:
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[db_module.get_db] = _get_db
    app.dependency_overrides[current_user] = lambda: test_user
    app.dependency_overrides[get_razorpay_client] = lambda: FakeRazorpayClient()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(engine, session, admin_user) -> TestClient:
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[db_module.get_db] = _get_db
    app.dependency_overrides[current_user] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    yield TestClient(app)
    app.dependency_overrides.clear()
