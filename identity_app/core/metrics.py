"""Bounded Prometheus signals defined by DIDDI Observability v1."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, Info, generate_latest

from identity_app.core.observability import service_identity

HTTP_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
JOB_DURATION_BUCKETS = (0.1, 1, 5, 15, 60, 300, 900, 3600)
_KNOWN_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})

SERVICE_INFO = Info("diddi_service", "DIDDI service resource identity.")
HTTP_REQUESTS = Counter(
    "diddi_http_server_requests",
    "Total completed HTTP server requests.",
    ("method", "route", "status_code"),
)
HTTP_REQUEST_DURATION = Histogram(
    "diddi_http_server_request_duration_seconds",
    "Completed HTTP server request duration in seconds.",
    ("method", "route"),
    buckets=HTTP_DURATION_BUCKETS,
)
DEPENDENCY_REQUESTS = Counter(
    "diddi_dependency_requests",
    "Dependency probes and calls completed by outcome.",
    ("dependency", "operation", "outcome"),
)
DEPENDENCY_REQUEST_DURATION = Histogram(
    "diddi_dependency_request_duration_seconds",
    "Dependency probe and call duration in seconds.",
    ("dependency", "operation"),
    buckets=HTTP_DURATION_BUCKETS,
)
JOBS = Counter("diddi_jobs", "Scheduled job executions.", ("job_type", "outcome"))
JOB_DURATION = Histogram(
    "diddi_job_duration_seconds",
    "Scheduled job duration in seconds.",
    ("job_type",),
    buckets=JOB_DURATION_BUCKETS,
)
WORKER_HEARTBEAT = Gauge(
    "diddi_worker_heartbeat_timestamp_seconds",
    "Unix timestamp of the latest completed worker loop.",
    ("worker_type",),
)
TELEMETRY_DROPPED = Counter(
    "diddi_telemetry_dropped",
    "Telemetry signals dropped or rejected before delivery.",
    ("signal", "reason"),
)

# Service-specific additions remain separate from the shared DIDDI vocabulary.
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


def configure_metrics(*, component: str | None = None) -> None:
    """Publish one bounded service-info series, never per user or request."""

    SERVICE_INFO.info(service_identity(component=component).as_metric_labels())


def route_template(scope: dict) -> str:
    """Use router templates and one fallback to keep label cardinality bounded."""

    route = scope.get("route")
    template = getattr(route, "path", None)
    return template or "/_unmatched"


def metric_method(method: str) -> str:
    normalized = method.upper()
    return normalized if normalized in _KNOWN_METHODS else "OTHER"


def observe_http_request(*, method: str, route: str, status_code: int, duration_seconds: float) -> None:
    normalized_method = metric_method(method)
    HTTP_REQUESTS.labels(normalized_method, route, str(status_code)).inc()
    HTTP_REQUEST_DURATION.labels(normalized_method, route).observe(duration_seconds)


def observe_dependency_request(
    *,
    dependency: str,
    operation: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    DEPENDENCY_REQUESTS.labels(dependency, operation, outcome).inc()
    DEPENDENCY_REQUEST_DURATION.labels(dependency, operation).observe(duration_seconds)


def observe_job(*, job_type: str, outcome: str, duration_seconds: float) -> None:
    JOBS.labels(job_type, outcome).inc()
    JOB_DURATION.labels(job_type).observe(duration_seconds)


def observe_worker_heartbeat(*, worker_type: str, timestamp_seconds: float) -> None:
    WORKER_HEARTBEAT.labels(worker_type).set(timestamp_seconds)


def observe_telemetry_dropped(*, signal: str, reason: str, count: int = 1) -> None:
    TELEMETRY_DROPPED.labels(signal, reason).inc(count)


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
