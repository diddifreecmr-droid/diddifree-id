# DiddiFreeID Observability Runbook

## First connection

1. Inject the values listed in `docs/OBSERVABILITY.md` through the deployment secret store, including a mounted trusted CA path for OTLP.
2. Deploy a unique immutable `SERVICE_VERSION`, `ENVIRONMENT` and `DIDDI_DEPLOYMENT_ID`.
3. Confirm `/health/live`, `/health/ready` and `/metrics` with the scraper credential from inside the observability network.
4. Mount `OBSERVABILITY_LOG_VOLUME_NAME` read-only in DiddiObserve and collect `/var/log/diddifree/observability.jsonl`; do not add a Docker socket.
5. Generate one safe test request with an `X-Request-ID`; find its JSON log, metric increment and trace in DiddiObserve.

## Incident checks

1. Liveness failure: investigate the API process/container.
2. Readiness failure: inspect only the named dependency status; do not expose DSNs, provider responses or credentials in tickets.
3. Worker stale: run `account-purger` once, then inspect Redis connectivity and the worker exit code.
4. Missing telemetry: verify collector reachability and credentials. Business requests must remain available while the collector is unavailable.

## Escalation

Use the contact referenced by `DIDDIFREE_ID_OPERATIONS_CONTACT`. DiddiObserve owns central retention, backups, alert routing and dashboard availability.
