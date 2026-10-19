"""Prometheus metrics kept deliberately small for the first observability step."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "diddifree_http_requests",
    "Total HTTP requests handled by DiddiFreeID.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "diddifree_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
)
CAPABILITY_EVENTS = Counter(
    "diddifree_capability_events",
    "Capability projection operations handled by DiddiFreeID.",
    ("operation", "result", "service"),
)
CAPABILITY_STALE_READS = Counter(
    "diddifree_capability_stale_reads",
    "Capability rows returned after the configured freshness window.",
    ("service",),
)
SERVICE_TOKEN_ISSUANCE = Counter(
    "diddifree_service_token_issuance",
    "Service-token issuance attempts handled by DiddiFreeID.",
    ("service", "result"),
)
OTP_DELIVERIES = Counter(
    "diddifree_otp_deliveries",
    "OTP delivery attempts handled by DiddiFreeID.",
    ("channel", "provider", "result"),
)
EVENT_PUBLISH = Counter(
    "diddifree_event_publish",
    "Domain event publication attempts handled by DiddiFreeID.",
    ("event", "result"),
)
DEPENDENCY_HEALTH = Gauge(
    "diddifree_dependency_health",
    "Current readiness state of a DiddiFreeID dependency (1 healthy, 0 unhealthy).",
    ("dependency",),
)


def route_template(scope: dict) -> str:
    """Use route templates to avoid high-cardinality user-id labels."""

    route = scope.get("route")
    template = getattr(route, "path", None)
    return template or "unmatched"


def observe_http_request(*, method: str, route: str, status_code: int, duration_seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
    HTTP_REQUEST_DURATION.labels(method, route).observe(duration_seconds)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def observe_capability_event(*, operation: str, result: str, service: str) -> None:
    CAPABILITY_EVENTS.labels(operation, result, service).inc()


def observe_capability_stale_read(*, service: str) -> None:
    CAPABILITY_STALE_READS.labels(service).inc()


def observe_service_token_issuance(*, service: str, result: str) -> None:
    SERVICE_TOKEN_ISSUANCE.labels(service, result).inc()


def observe_otp_delivery(*, channel: str, provider: str, result: str) -> None:
    OTP_DELIVERIES.labels(channel, provider, result).inc()


def observe_event_publish(*, event: str, result: str) -> None:
    EVENT_PUBLISH.labels(event, result).inc()


def observe_dependency_health(*, dependency: str, healthy: bool) -> None:
    DEPENDENCY_HEALTH.labels(dependency).set(1 if healthy else 0)
