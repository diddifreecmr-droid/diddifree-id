# DiddiFreeID service-token runbook

This runbook covers staging and production operations for DiddiFreeID
`client_credentials` service tokens, with Pilotage as the first consumer.

## Scope

DiddiFreeID owns:

- the service-client registry;
- secret hashing and rotation;
- service-token issuance;
- JWKS publication;
- the identity reporting endpoint used by Pilotage:
  `GET /identity/v1/internal/pilotage/identity-summary`.

Consumer modules own their own API authorization after they verify a service
token. DiddiFreeID does not grant business permissions outside its own
endpoints.

## Client inventory

Each service client is environment-specific. Do not reuse a staging secret in
production, and do not reuse a secret across target services.

For Pilotage there are separate clients per target:

- `pilotage-staging-diddifreeid`: `aud=diddifree-id`, scope
  `identity:reporting:read`;
- `pilotage-staging-diddigo`: `aud=diddigo`, DiddiGo reporting scopes;
- production clients must use distinct `*-prod-*` names and secrets.

Secrets are stored only in the environment secret store. Never paste plaintext
secrets into Git, Jira, logs, dashboards, screenshots, or runbook evidence.

## Health checks

Use:

```text
GET /health/live
GET /health/ready
GET /metrics
```

Expected readiness dependencies:

- PostgreSQL: available;
- Redis: available;
- JWT key material: loaded;
- OTP provider status: reported according to configured provider.

`/ready` is not the canonical path. Use `/health/ready`.

## Metrics

Prometheus metrics exposed by `/metrics` include:

- `diddifree_http_requests_total{method,route,status_code}`;
- `diddifree_http_request_duration_seconds{method,route}`;
- `diddifree_service_token_issuance_total{service,result}`;
- `diddifree_capability_events_total{operation,result,service}`;
- `diddifree_capability_stale_reads_total{service}`.

Service-token issuance `result` values:

- `issued`;
- `unsupported_grant_type`;
- `invalid_client`;
- `invalid_audience`;
- `invalid_scope`.

Before a client is authenticated, the service label is `unknown`. This avoids
turning metrics into a client-id oracle.

## Suggested alerts

Tune thresholds to traffic volume. Initial staging suggestions:

- Any sustained increase of
  `diddifree_service_token_issuance_total{result="invalid_client"}` over
  5 minutes.
- Any `invalid_audience` or `invalid_scope` after a deployment.
- Any sustained 5xx on
  `route="/identity/v1/auth/service/token"`.
- Any sustained 401 or 403 on
  `route="/identity/v1/internal/pilotage/identity-summary"`.
- No successful Pilotage collection within the expected collection window.
  This is consumer-side too: Pilotage should alert when its latest successful
  pull is stale.

## Common diagnosis

### Token issuance returns `401 INVALID_CLIENT`

Check, without exposing secrets:

1. `X-Client-ID` equals form `client_id`.
2. Client exists in the service-client registry.
3. Client is active and `revoked_at` is null.
4. Client is not expired.
5. Secret in the consumer stack matches the current secret hash.
6. Consumer is using the correct environment secret.

Do not log or paste the plaintext secret. Rotate if in doubt.

### Token issuance returns `403 INVALID_AUDIENCE`

Check that the requested `audience` is present in the client's allowlist.
For Pilotage reading DiddiFreeID identity metrics, the audience is
`diddifree-id`.

### Token issuance returns `403 INVALID_SCOPE`

Check that every requested scope is present in the client's allowlist.
For Pilotage identity metrics, use only `identity:reporting:read`.

### Reporting endpoint returns `401 TOKEN_EXPIRED`

The consumer reused an expired service token. Service tokens are short-lived
and have no refresh flow. The consumer must request a new token.

### Reporting endpoint returns `401 SERVICE_CLIENT_ID_INVALID`

The `X-Client-ID` header does not match the `client_id` claim in the service
token, or the header is missing.

### Reporting endpoint returns `403 SERVICE_REPORTING_FORBIDDEN`

The service token is valid but the service claim is not `pilotage`.

### Reporting endpoint returns `403 SERVICE_SCOPE_INVALID`

The service token lacks `identity:reporting:read`.

## Rotation procedure

Use this when a secret is old, suspected exposed, or when performing scheduled
rotation.

1. Confirm the client id and target environment.
2. Generate a new secret through the admin rotation endpoint:

```text
POST /identity/v1/admin/service-clients/{client_id}/secret/rotate
```

3. Store the returned plaintext secret immediately in the environment secret
   store. It is returned once.
4. Update the consumer stack configuration.
5. Let the user redeploy the consumer stack. Codex must not deploy Portainer
   unless explicitly authorized.
6. Smoke test:

```text
POST /identity/v1/auth/service/token
GET /identity/v1/internal/pilotage/identity-summary?date=YYYY-MM-DD
```

7. Confirm old secret is rejected with `401 INVALID_CLIENT`.
8. Keep evidence: date, environment, client id, HTTP status, request id, and
   non-sensitive response summary. Do not include the secret.

Already-issued tokens remain valid until their short expiration. Rotation does
not create a refresh token and does not reactivate a revoked client.

## Revocation procedure

Use revocation when a client should stop receiving new tokens immediately.

1. Disable the service client:

```text
PATCH /identity/v1/admin/service-clients/{client_id}
{"active": false}
```

2. Confirm token issuance now returns `401 INVALID_CLIENT`.
3. Remember: already-issued service tokens remain valid until their short
   expiration unless a separate denylist/introspection layer is introduced.
4. To re-enable after investigation:

```text
PATCH /identity/v1/admin/service-clients/{client_id}
{"active": true}
```

Re-enable only after rotating the secret when exposure is possible.

## Staging evidence checklist

For each staging validation, record:

- date and environment;
- client id, never secret;
- route and status code;
- functional error code;
- request id when available;
- summary of successful response;
- confirmation that no production client or secret was touched.

