# Diddi Observability v1 - DiddiFreeID

This module implements the local portion of `DIDDI Observability v1`. Its
canonical identity is `diddi/diddifree-id`; `diddiauth` is not a service name.
The versioned manifest is `observability/diddifree-id.observability.v1.yaml`.

## Local signals

- Logs are single-line JSON on stdout, UTC, schema `1.0.0`, with the complete
  eight-field resource identity. `X-Request-ID` takes precedence over the
  accepted `X-Correlation-ID` alias and is returned on the response.
- Credentials, headers and request bodies are not logged. `OTP_LOG_PLAINTEXT`
  remains an explicit staging exception: when true, OTP senders emit
  `otp.code` and `otp.recipient`; when false, neither field is emitted.
- `/metrics` is Prometheus text protected by `Authorization: Bearer
  <METRICS_AUTH_TOKEN>`; it closes with `503` when the secret is absent.
- Traces are optional OTLP/HTTP batches. Their queue is bounded to 2048, export
  is attempted every five seconds and an unavailable collector only drops
  telemetry.
- `/health/live` is process-only. `/health/ready` checks PostgreSQL, Redis,
  migrations, JWT keys and OTP configuration. `/health/workers` separately
  checks the Redis heartbeat of `account-purger`.

## DiddiObserve handoff

The central platform must provide through Portainer or the secret manager,
never through Git:

| Value | Purpose |
| --- | --- |
| `METRICS_AUTH_TOKEN` | scraper bearer credential |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | full OTLP HTTP trace endpoint |
| `OTEL_EXPORTER_OTLP_HEADERS` | collector auth headers when required |
| `DIDDI_DEPLOYMENT_ID` | deployment identifier |
| `DIDDIFREE_ID_OPERATIONS_CONTACT` | on-call contact referenced by the manifest |

Set `OTEL_ENABLED=true`, use `OTEL_TRACE_SAMPLE_RATIO=1.0` during validation
and `0.1` in production. Set immutable `SERVICE_VERSION` and `ENVIRONMENT` for
every deploy. The collector scrapes `api:8000/metrics` with the configured
Bearer credential. These changes are prepared in Compose only; no Portainer
deployment is performed by this repository change.

## Verification status

Local tests cover JSON redaction/correlation, metric authorization and bounded
route labels, health semantics, worker heartbeats, async producer metadata and
best-effort trace setup. C01-C05, C08-C10 are locally implementable; C06 needs
a downstream service, C07 consumer validation is not applicable here, and
C11-C12 remain central-platform work. Do not mark the service fully conformant
before DiddiObserve confirms correlated log/metric/trace ingestion and the
end-to-end outage test. C03 is non-conformant while `OTP_LOG_PLAINTEXT=true`.
