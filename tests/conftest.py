"""Pytest fixtures for the DiddiFreeID suite.

Strategy, mirroring DiddiGo's so the two suites feel like one:

  * tests run against the real Postgres and Redis from docker-compose, on a
    dedicated `diddi_free_id_test` database. Schema-qualified tables, server
    defaults and UNIQUE constraints are then exercised for real — SQLite would
    quietly accept things Postgres rejects;
  * the schema is built once per session by running Alembic against that
    database, so the migration itself is under test on every run;
  * `client` binds httpx to the ASGI app in-process, with no network;
  * `otp_code` captures the plaintext code the SMS stub logs, which is how a
    test completes a verification without an SMS provider.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

# Settings are read at import time, so every environment value the app depends
# on must be set before the first `identity_app.*` import below.
TEST_DB_NAME = "diddi_free_id_test"
ADMIN_DSN = "postgresql://postgres:postgres@localhost:5435/postgres"
TEST_DSN_SYNC = f"postgresql://postgres:postgres@localhost:5435/{TEST_DB_NAME}"
TEST_DSN_ASYNC = f"postgresql+asyncpg://postgres:postgres@localhost:5435/{TEST_DB_NAME}"

os.environ["DATABASE_URL"] = TEST_DSN_ASYNC
os.environ.setdefault("REDIS_URL", "redis://localhost:6381/1")
# Rate limiting off by default so back-to-back OTP requests in a test do not
# 429. `test_rate_limiting.py` turns it back on explicitly for its own case.
os.environ.setdefault("OTP_RATE_LIMIT_SECONDS", "0")
os.environ.setdefault("OTP_HASH_PEPPER", "test-pepper-at-least-32-characters-long")
os.environ.setdefault("OTP_LOG_PLAINTEXT", "true")
os.environ.setdefault("JWT_PRIVATE_KEY_PATH", "keys/private.pem")
os.environ.setdefault("JWT_PUBLIC_KEY_PATH", "keys/public.pem")
os.environ.setdefault("JWT_ACTIVE_KID", "dev-2026-07-01")
# Exercises the service-to-service path of contract §5.
SERVICE_KEY = "test-service-key"
os.environ.setdefault("SERVICE_API_KEYS", SERVICE_KEY)

API = "/identity/v1"


def _recreate_test_database() -> None:
    """Drop and recreate the test database, with the extension and schema the
    migration expects to find (the compose init script never runs for it)."""
    import psycopg

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB_NAME,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    with psycopg.connect(TEST_DSN_SYNC, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')


def _run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DSN_ASYNC)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    _recreate_test_database()
    _run_migrations()
    yield


@pytest.fixture(autouse=True)
async def clean_redis() -> AsyncIterator[None]:
    """Wipe cached profiles and rate-limit counters between tests.

    Without this, a profile cached by one test answers a query in the next and
    results depend on execution order — the worst kind of flake to chase.
    """
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings

    redis = create_redis_pool(settings.redis_url)
    await redis.flushdb()
    try:
        yield
    finally:
        await redis.flushdb()
        await redis.aclose()


@pytest.fixture
async def client(database) -> AsyncIterator[httpx.AsyncClient]:
    from identity_app.core.database import engine
    from identity_app.core.redis import create_redis_pool
    from identity_app.core.settings import settings
    from identity_app.main import app
    from identity_app.modules.identity.infra.token_service import TokenService

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        # The lifespan does not run under ASGITransport, so mount what the
        # routes expect on app.state by hand — mirroring `core.lifespan`.
        app.state.redis = create_redis_pool(settings.redis_url)
        app.state.tokens = TokenService()
        try:
            yield c
        finally:
            await app.state.redis.aclose()
            # pytest-asyncio gives each test its own event loop, while `engine`
            # is module-level and pools asyncpg connections bound to the loop
            # that opened them. Reusing those in the next test raises
            # `AttributeError: 'NoneType' object has no attribute 'send'` on the
            # Windows proactor loop, so drop the pool between tests.
            await engine.dispose()


OTP_LOGGER = "identity_app.modules.identity.infra.sms_adapter"


class OtpCapture(logging.Handler):
    """Records the plaintext code the SMS stub logs.

    Its own handler rather than pytest's `caplog` because `caplog` only sees
    records emitted inside the test body, and the fixtures below request codes
    during setup.
    """

    _PATTERN = re.compile(r"est (\d{6})\.")

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.codes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        match = self._PATTERN.search(record.getMessage())
        if match:
            self.codes.append(match.group(1))

    def latest(self) -> str:
        if not self.codes:
            raise AssertionError("Aucun code OTP journalisé — request_otp a-t-il tourné ?")
        return self.codes[-1]


@pytest.fixture
def otp_code() -> Iterator[OtpCapture]:
    handler = OtpCapture()
    logger = logging.getLogger(OTP_LOGGER)
    previous_level = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.fixture
def phone_factory():
    """Unique numbers, so tests never collide on the UNIQUE constraint."""

    def _make(prefix: str = "+22507") -> str:
        return f"{prefix}{uuid.uuid4().int % 10_000_000:07d}"

    return _make


async def register_and_verify(
    client: httpx.AsyncClient,
    otp_code: OtpCapture,
    phone: str,
    full_name: str = "Awa Koné",
) -> dict:
    """Run the full signup and return the `/auth/otp/verify` body."""
    r = await client.post(f"{API}/auth/register", json={"phone": phone, "full_name": full_name})
    assert r.status_code == 201, r.text

    r = await client.post(f"{API}/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text

    r = await client.post(
        f"{API}/auth/otp/verify",
        json={"phone": phone, "code": otp_code.latest()},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
async def user_session(client, otp_code, phone_factory) -> dict:
    """A verified, active user: tokens plus an Authorization header."""
    body = await register_and_verify(client, otp_code, phone_factory())
    return {
        "user": body["user"],
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


@pytest.fixture
async def admin_session(client, otp_code, phone_factory) -> dict:
    """An admin.

    Promoted through the service-to-service role route rather than by writing
    to the database directly: bootstrapping the first admin is an ops action,
    and going through the real endpoint keeps the fixture honest about what
    that action actually is.
    """
    body = await register_and_verify(client, otp_code, phone_factory("+22509"))
    user_id = body["user"]["id"]

    r = await client.patch(
        f"{API}/users/{user_id}/role",
        json={"role": "admin", "reason": "Bootstrap administrateur (tests)"},
        headers={"X-Service-Key": SERVICE_KEY},
    )
    assert r.status_code == 200, r.text

    return {
        "user": r.json(),
        "access_token": body["access_token"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }
