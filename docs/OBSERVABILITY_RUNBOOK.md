# DiddiFreeID Observability Runbook

## First connection

1. Inject the values listed in `docs/OBSERVABILITY.md` through the deployment secret store. The standard HTTPS DiddiObserve endpoint uses the image trust store; set `OTEL_EXPORTER_OTLP_CERTIFICATE` only for an explicitly approved private CA.
2. Deploy a unique immutable `SERVICE_VERSION`, `ENVIRONMENT` and `DEPLOYMENT_ID`.
3. Confirm `/health/live`, `/health/ready` and `/metrics` with the scraper credential from inside the observability network.
4. Mount `OBSERVABILITY_LOG_VOLUME_NAME` read-only in DiddiObserve and collect only `/var/log/diddifree/observability-api.jsonl` and `/var/log/diddifree/observability-worker.jsonl`; persist collector positions and do not add a Docker socket.
5. Generate one safe test request with an `X-Request-ID`; find its JSON log, metric increment and trace in DiddiObserve.
6. Test the `account-purger` separately and verify it writes only its worker file. Do not configure a second central log transport for the same events.

## OTP exception

If `OTP_LOG_PLAINTEXT=true`, central collection requires an explicit approval
for the OTP code and recipient fields, including access and retention. The
preferred connection state is `OTP_LOG_PLAINTEXT=false`; changing it requires
a redeploy of the API and worker. Do not backfill historical OTP-containing
files.

## Incident checks

1. Liveness failure: investigate the API process/container.
2. Readiness failure: inspect only the named dependency status; do not expose DSNs, provider responses or credentials in tickets.
3. Worker stale: run `account-purger` once, then inspect Redis connectivity and the worker exit code.
4. Missing telemetry: verify collector reachability and credentials. Business requests must remain available while the collector is unavailable.

## Escalation

Use the contact referenced by `DIDDIFREE_ID_OPERATIONS_CONTACT`. DiddiObserve owns central retention, backups, alert routing and dashboard availability.
