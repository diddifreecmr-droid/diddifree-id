# Diddi Observability 2.0.0 - DiddiFreeID

This module implements the local portion of `DIDDI Observability 2.0.0`. Its
canonical identity is `diddi/diddifree-id`; `diddiauth` is not a service name.
The versioned manifest is `observability/diddifree-id.observability.v1.yaml`.

## Local signals

- Logs are normalized once by the existing JSON formatter, then exported in
  bounded OTLP HTTP/protobuf batches when both `OTEL_ENABLED=true` and
  `OTEL_LOGS_ENABLED=true`. The same cleaned event remains available on stdout
  and in the optional rotating JSONL files for local diagnosis only.
- The API reapplies logging configuration during FastAPI lifespan, after
  Uvicorn setup. `uvicorn.error`, application and library events propagate once
  to the root handler; `uvicorn.access` remains disabled to avoid duplicating
  the normalized HTTP completion event.
- Credentials, headers and request bodies are not logged. `OTP_LOG_PLAINTEXT`
  remains an explicit staging exception: when true, OTP senders emit
  `otp.code` and `otp.recipient`; when false, neither field is emitted.
- `/metrics` is Prometheus text protected by `Authorization: Bearer
  <METRICS_BEARER_TOKEN>`; it closes with `503` when the secret is absent.
  `METRICS_AUTH_TOKEN` remains accepted during migration.
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
| `METRICS_BEARER_TOKEN` | scraper bearer credential |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | full OTLP HTTP trace endpoint, if set |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | base OTLP URL, used only when the specific trace URL is empty |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | full OTLP HTTP/protobuf logs endpoint, if set |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | must be `http/protobuf` |
| `OTEL_LOGS_ENABLED` | explicit log-export activation; requires `OTEL_ENABLED=true` |
| `OTEL_EXPORTER_OTLP_HEADERS` | collector auth headers when required |
| `OTEL_EXPORTER_OTLP_CERTIFICATE` | optional mounted private CA path; leave empty for standard public HTTPS |
| `DEPLOYMENT_ID` | deployment identifier |
| `DIDDIFREE_ID_OPERATIONS_CONTACT` | on-call contact referenced by the manifest |

Set `OTEL_ENABLED=true` and `OTEL_LOGS_ENABLED=true`, use
`OTEL_TRACE_SAMPLE_RATIO=1.0` during validation and `0.1` in production. Set immutable `SERVICE_VERSION`, `ENVIRONMENT` and
`DEPLOYMENT_ID` for every deploy. The collector scrapes `api:8000/metrics` with
the configured Bearer credential. The official HTTPS endpoint uses the image's
standard trust store; never disable TLS verification. `OTEL_EXPORTER_OTLP_HEADERS`
is shared by the logs and traces exporters, but remains distinct from the metrics
Bearer token.

DiddiObserve must first validate a canary excluded from its legacy file collector.
It must then disable its JSONL volume collection before enabling general OTLP Logs
for this service. The local files `observability-api.jsonl` and
`observability-worker.jsonl` remain for troubleshooting but must not be collected
centrally after the cutover.

## OTP diagnostic exception

`OTP_LOG_PLAINTEXT=true` is a temporary staging-only diagnostic switch. It
causes `otp.delivery.dispatched` events to contain `attributes.otp.code` and
`attributes.otp.recipient`. Its authorized readers are DiddiFreeID staging
operators with explicit log access; no password, JWT, service secret or other
credential is covered by this exception. The normal local retention is bounded
by the two per-process file rotations (10 MiB active plus five archives).

The central OTLP pipeline must test `otp.code` and `otp.recipient` only with
synthetic values and record its access and retention policy. Historical local
files must never be backfilled. Disable the exception by setting
`OTP_LOG_PLAINTEXT=false` in Portainer and redeploying the API and worker.

## Verification status

Local tests cover JSON redaction/correlation, metric authorization and bounded
route labels, health semantics, worker heartbeats, async producer metadata and
best-effort trace/log setup. C01-C05, C08-C10 are locally implementable; C06 needs
a downstream service, C07 consumer validation is not applicable here, and
C11-C12 remain central-platform work. Do not mark the service fully conformant
before DiddiObserve confirms correlated log/metric/trace ingestion and the
end-to-end outage test. C03 remains an explicit exception while
`OTP_LOG_PLAINTEXT=true`.
