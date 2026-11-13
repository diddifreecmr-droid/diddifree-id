"""Best-effort OpenTelemetry tracing for DiddiFreeID.

Tracing is deliberately optional. A missing or unreachable DiddiObserve
collector must only drop telemetry, never affect identity operations.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from opentelemetry import context, propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from identity_app.core.observability import service_identity
from identity_app.core.settings import settings

logger = logging.getLogger(__name__)
_configured = False


def _headers() -> dict[str, str]:
    """Parse OTLP headers without ever logging their values."""

    result: dict[str, str] = {}
    for item in settings.otel_exporter_otlp_headers.split(","):
        key, separator, value = item.partition("=")
        if separator and key.strip() and value.strip():
            result[key.strip()] = value.strip()
    return result


def configure_tracing(app: FastAPI) -> bool:
    """Configure tracing once, returning false when it is intentionally off.

    Export runs through a batch processor; exporter outages are handled outside
    request execution and only cause spans to be discarded.
    """

    global _configured
    if _configured:
        return True
    if not settings.otel_enabled:
        logger.info("tracing_disabled", extra={"event": "observability.tracing.disabled"})
        return False
    if not settings.otel_exporter_otlp_traces_endpoint:
        logger.warning(
            "tracing_endpoint_missing",
            extra={"event": "observability.tracing.endpoint_missing"},
        )
        return False

    try:
        identity = service_identity()
        resource = Resource.create(
            {
                "service.name": identity.service_name,
                "service.version": identity.service_version,
                "deployment.environment.name": identity.environment,
                "service.instance.id": identity.instance_id,
                "diddifree.component": identity.component,
            },
        )
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(TraceIdRatioBased(settings.otel_trace_sample_ratio)),
        )
        exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_traces_endpoint,
            headers=_headers(),
            timeout=settings.otel_export_timeout_seconds,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
        _configured = True
        logger.info("tracing_configured", extra={"event": "observability.tracing.configured"})
        return True
    except Exception:
        # An observability setup defect must never take the identity service
        # down. Operators still receive a local structured error log.
        logger.exception("tracing_configuration_failed", extra={"event": "observability.tracing.failed"})
        return False


def shutdown_tracing() -> None:
    """Flush best-effort spans when the process is stopping."""

    if not _configured:
        return
    try:
        provider = trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if force_flush is not None:
            force_flush(timeout_millis=int(settings.otel_export_timeout_seconds * 1000))
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is not None:
            shutdown()
    except Exception:
        logger.warning(
            "tracing_shutdown_failed",
            exc_info=True,
            extra={"event": "observability.tracing.shutdown_failed"},
        )


def inject_trace_context() -> dict[str, str]:
    """Return W3C headers for an asynchronous event envelope."""

    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {key: value for key, value in carrier.items() if key in {"traceparent", "tracestate"}}


@contextmanager
def consume_event_trace_context(headers: dict[str, str], name: str) -> Iterator[None]:
    """Resume a propagated Redis Stream trace in a consuming worker.

    DiddiFreeID currently publishes domain events but does not consume them.
    The helper keeps the cross-service contract explicit for future local
    consumers without changing the published domain-event payload.
    """

    extracted = propagate.extract(headers)
    token = context.attach(extracted)
    try:
        with trace.get_tracer(__name__).start_as_current_span(name):
            yield
    finally:
        context.detach(token)


def current_trace_fields() -> dict[str, str]:
    """Expose safe trace identifiers for structured logs only."""

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": f"{span_context.trace_id:032x}",
        "span_id": f"{span_context.span_id:016x}",
    }
