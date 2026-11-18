"""Stable observability identity shared by logs, metrics and traces."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import uuid4

from identity_app.core.settings import settings

CANONICAL_SERVICE_NAME = "diddifree-id"
OBSERVABILITY_SCHEMA_VERSION = "1.0.0"
# This identifies the adopted platform contract. It is intentionally separate
# from the immutable JSON log schema above.
DIDDI_OBSERVABILITY_CONTRACT_VERSION = "1.2.1"
_PROCESS_INSTANCE_ID = f"{os.getenv('HOSTNAME', 'process')}-{uuid4().hex}"


@dataclass(frozen=True)
class ServiceIdentity:
    """Non-secret resource attributes attached to every emitted signal."""

    service_namespace: str
    service_name: str
    service_version: str
    instance_id: str
    environment: str
    deployment_id: str
    component: str
    observability_version: str

    def as_resource_attributes(self) -> dict[str, str]:
        return {
            "service.namespace": self.service_namespace,
            "service.name": self.service_name,
            "service.version": self.service_version,
            "service.instance.id": self.instance_id,
            "deployment.environment.name": self.environment,
            "diddi.deployment.id": self.deployment_id,
            "diddi.component": self.component,
            "diddi.observability.version": self.observability_version,
        }

    def as_metric_labels(self) -> dict[str, str]:
        """Prometheus labels cannot contain dots used by resource attributes."""

        return {
            "service_namespace": self.service_namespace,
            "service_name": self.service_name,
            "service_version": self.service_version,
            "deployment_environment_name": self.environment,
            "deployment_id": self.deployment_id,
            "component": self.component,
            "instance": self.instance_id,
            "observability_version": self.observability_version,
        }


def service_identity(*, component: str | None = None) -> ServiceIdentity:
    """Return the canonical identity without exposing configuration secrets."""

    configured_name = settings.otel_service_name.strip() or CANONICAL_SERVICE_NAME
    if configured_name != CANONICAL_SERVICE_NAME:
        raise ValueError("OTEL_SERVICE_NAME doit être diddifree-id.")

    return ServiceIdentity(
        service_namespace="diddi",
        service_name=CANONICAL_SERVICE_NAME,
        service_version=settings.service_version,
        # An operator value is a deployment hint, never a reusable instance
        # identifier. The process suffix guarantees renewal after restart.
        instance_id=(
            f"{settings.service_instance_id}-{_PROCESS_INSTANCE_ID}"
            if settings.service_instance_id
            else _PROCESS_INSTANCE_ID
        ),
        environment=settings.environment,
        deployment_id=settings.diddi_deployment_id or f"{CANONICAL_SERVICE_NAME}-{settings.environment}",
        component=component or settings.observability_component,
        observability_version=DIDDI_OBSERVABILITY_CONTRACT_VERSION,
    )
