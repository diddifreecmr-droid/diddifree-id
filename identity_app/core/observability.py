"""Stable observability identity shared by logs, metrics and traces."""

from __future__ import annotations

import os
from dataclasses import dataclass

from identity_app.core.settings import settings

CANONICAL_SERVICE_NAME = "diddifree-id"


@dataclass(frozen=True)
class ServiceIdentity:
    """Non-secret resource attributes attached to every emitted signal."""

    service_name: str
    service_version: str
    environment: str
    instance_id: str
    component: str

    def as_dict(self) -> dict[str, str]:
        return {
            "service": self.service_name,
            "service_version": self.service_version,
            "environment": self.environment,
            "instance_id": self.instance_id,
            "component": self.component,
        }


def service_identity(*, component: str | None = None) -> ServiceIdentity:
    """Return the canonical identity without exposing configuration secrets."""

    return ServiceIdentity(
        service_name=CANONICAL_SERVICE_NAME,
        service_version=settings.service_version,
        environment=settings.environment,
        instance_id=settings.service_instance_id or os.getenv("HOSTNAME", "unknown"),
        component=component or settings.observability_component,
    )
