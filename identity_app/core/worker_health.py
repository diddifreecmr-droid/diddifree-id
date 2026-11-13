"""Redis-backed worker heartbeats used by the API and container healthchecks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from identity_app.core.metrics import observe_worker_heartbeat
from identity_app.core.settings import settings

WORKER_HEALTH_PREFIX = "identity:observability:worker:"


def _now() -> datetime:
    return datetime.now(UTC)


def _key(worker: str) -> str:
    return f"{WORKER_HEALTH_PREFIX}{worker}"


async def record_worker_heartbeat(
    redis: Redis,
    *,
    worker: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Store a bounded, non-sensitive heartbeat for a periodic worker."""

    now = _now()
    payload = {
        "worker": worker,
        "status": status,
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "details": details or {},
    }
    await redis.set(_key(worker), json.dumps(payload), ex=settings.worker_heartbeat_ttl_seconds)
    if status == "ok":
        observe_worker_heartbeat(worker_type=worker, timestamp_seconds=now.timestamp())


async def worker_health_report(redis: Redis, *, worker: str) -> dict[str, Any]:
    """Return a safe worker status and mark stale heartbeats unhealthy."""

    raw = await redis.get(_key(worker))
    if not raw:
        return {"status": "missing", "worker": worker}
    try:
        payload = json.loads(raw)
        updated_at = datetime.fromisoformat(payload["updated_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "error", "worker": worker}

    age_seconds = max(0.0, (_now() - updated_at).total_seconds())
    healthy = payload.get("status") == "ok" and age_seconds <= settings.worker_heartbeat_stale_seconds
    if payload.get("status") == "ok":
        observe_worker_heartbeat(worker_type=worker, timestamp_seconds=updated_at.timestamp())
    return {
        "status": "ok" if healthy else ("stale" if age_seconds > settings.worker_heartbeat_stale_seconds else "error"),
        "worker": worker,
        "updated_at": payload["updated_at"],
        "age_seconds": round(age_seconds, 3),
    }
