"""Pilotage read model for identity-level usage metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from identity_app.core.settings import settings
from identity_app.modules.identity.infra.read_repository import SqlAlchemyUserReadRepository


@dataclass
class GetIdentitySummary:
    users: SqlAlchemyUserReadRepository

    async def __call__(self, *, day: date) -> dict:
        timezone = ZoneInfo(settings.identity_reporting_timezone)
        local_start = datetime.combine(day, time.min, tzinfo=timezone)
        local_end = local_start + timedelta(days=1)
        month_start = day.replace(day=1)
        now = datetime.now(timezone)

        metrics = await self.users.identity_summary(
            day_start=local_start,
            day_end=local_end,
            activity_day=day,
            activity_month_start=month_start,
            activity_month_end=day,
        )
        return {
            "contract_version": "pilotage.v1",
            "module": "diddifree-id",
            "date": day.isoformat(),
            "timezone": settings.identity_reporting_timezone,
            "is_final": day < now.date(),
            "metrics": [
                {"name": name, "value": value, "unit": "count"}
                for name, value in metrics.items()
            ],
            "calculated_at": datetime.now(timezone).isoformat(),
            "sources": [{"module": "diddifree-id", "record_type": "identity-summary"}],
        }
