"""Readiness checks for the process and its critical dependencies."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy import text

from identity_app.core.database import engine
from identity_app.core.settings import settings


def _migration_heads() -> set[str]:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def _check_database() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
        result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        current_revisions = {row[0] for row in result}

    migrations_ok = current_revisions == _migration_heads()
    return {
        "status": "ok" if migrations_ok else "error",
        "migrations": "ok" if migrations_ok else "error",
    }


async def _check_redis(app: FastAPI) -> dict[str, str]:
    redis = getattr(app.state, "redis", None)
    if redis is None:
        return {"status": "error"}
    await redis.ping()
    return {"status": "ok"}


def _check_jwt_keys(app: FastAPI) -> dict[str, str]:
    try:
        tokens = getattr(app.state, "tokens", None)
        configured = bool(tokens and tokens.published_kids)
    except Exception:
        configured = False
    return {"status": "ok" if configured else "error"}


def _check_otp_provider() -> dict[str, str]:
    provider = settings.otp_provider.lower()
    configured = {
        "logging": True,
        "email": bool(settings.smtp_host and settings.smtp_username and settings.smtp_password),
        "smtp": bool(settings.smtp_host and settings.smtp_username and settings.smtp_password),
        "whatsapp": bool(
            settings.evolution_api_url
            and settings.evolution_api_key
            and settings.evolution_instance
        ),
        "telegram": bool(settings.telegram_bot_token),
    }.get(provider, False)
    return {"status": "ok" if configured else "error"}


async def _run_check(name: str, check) -> tuple[str, dict[str, str]]:
    try:
        return name, await asyncio.wait_for(check(), timeout=settings.health_check_timeout_seconds)
    except Exception:
        return name, {"status": "error"}


async def readiness_report(app: FastAPI) -> tuple[bool, dict[str, Any]]:
    """Run dependency checks concurrently and return a safe operations report."""

    checks = dict(
        await asyncio.gather(
            _run_check("database", _check_database),
            _run_check("redis", lambda: _check_redis(app)),
        ),
    )
    checks["jwt_keys"] = _check_jwt_keys(app)
    checks["otp_provider"] = _check_otp_provider()
    ready = all(check["status"] == "ok" for check in checks.values())
    return ready, checks
