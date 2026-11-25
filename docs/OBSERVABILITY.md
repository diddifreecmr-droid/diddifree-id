# Diddi Observability v1 - DiddiFreeID

This module implements the local portion of `DIDDI Observability v1.2.1`. Its
canonical identity is `diddi/diddifree-id`; `diddiauth` is not a service name.
The versioned manifest is `observability/diddifree-id.observability.v1.yaml`.

## Local signals

- Logs are single-line JSON on stdout and, when `OBSERVABILITY_LOG_FILE` is
  configured, a bounded rotating JSONL file. They include the complete
  eight-field resource identity. `X-Request-ID` takes precedence over the
  accepted `X-Correlation-ID` alias and is returned on the response.
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
| `OTEL_EXPORTER_OTLP_HEADERS` | collector auth headers when required |
| `OTEL_EXPORTER_OTLP_CERTIFICATE` | optional mounted private CA path; leave empty for standard public HTTPS |
| `DEPLOYMENT_ID` | deployment identifier |
| `DIDDIFREE_ID_OPERATIONS_CONTACT` | on-call contact referenced by the manifest |

Set `OTEL_ENABLED=true`, use `OTEL_TRACE_SAMPLE_RATIO=1.0` during validation
and `0.1` in production. Set immutable `SERVICE_VERSION`, `ENVIRONMENT` and
`DEPLOYMENT_ID` for every deploy. The collector scrapes `api:8000/metrics` with
the configured Bearer credential. The official HTTPS endpoint uses the image's
standard trust store; never disable TLS verification. The Portainer Compose
creates the named volume from `OBSERVABILITY_LOG_VOLUME_NAME`; DiddiObserve may
mount this exact volume read-only and collect only the active files
`observability-api.jsonl` and `observability-worker.jsonl`, without a Docker
socket. Each process owns a distinct rotating file.

The selected central log profile is `file-jsonl`, not OTLP logs. Leave
`OTEL_LOGS_ENABLED=false` and do not configure an additional central stdout or
OTLP log exporter, otherwise events would be duplicated. Traces use OTLP only.

## OTP diagnostic exception

`OTP_LOG_PLAINTEXT=true` is a temporary staging-only diagnostic switch. It
causes `otp.delivery.dispatched` events to contain `attributes.otp.code` and
`attributes.otp.recipient`. Its authorized readers are DiddiFreeID staging
operators with explicit log access; no password, JWT, service secret or other
credential is covered by this exception. The normal local retention is bounded
by the two per-process file rotations (10 MiB active plus five archives).

Before collecting these files centrally, the owner must either set
`OTP_LOG_PLAINTEXT=false` and redeploy, or explicitly approve a central
filtering, retention and access policy for those two fields. Historical OTP
lines must never be backfilled. Disable the exception by setting
`OTP_LOG_PLAINTEXT=false` in Portainer and redeploying the API and worker.

## Verification status

Local tests cover JSON redaction/correlation, metric authorization and bounded
route labels, health semantics, worker heartbeats, async producer metadata and
best-effort trace setup. C01-C05, C08-C10 are locally implementable; C06 needs
a downstream service, C07 consumer validation is not applicable here, and
C11-C12 remain central-platform work. Do not mark the service fully conformant
before DiddiObserve confirms correlated log/metric/trace ingestion and the
end-to-end outage test. C03 remains an explicit exception while
`OTP_LOG_PLAINTEXT=true`.
