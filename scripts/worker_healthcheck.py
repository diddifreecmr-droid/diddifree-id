"""Exit non-zero when a periodic DiddiFreeID worker is unhealthy or stale."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from identity_app.core.redis import create_redis_pool
from identity_app.core.settings import settings
from identity_app.core.worker_health import worker_health_report


async def main(worker: str) -> int:
    redis = create_redis_pool(settings.redis_url)
    try:
        report = await worker_health_report(redis, worker=worker)
        print(report["status"])
        return 0 if report["status"] == "ok" else 1
    finally:
        await redis.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/worker_healthcheck.py <worker>")
    raise SystemExit(asyncio.run(main(sys.argv[1])))
