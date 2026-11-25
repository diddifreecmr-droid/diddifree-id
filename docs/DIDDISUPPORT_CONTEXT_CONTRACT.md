# DiddiSupport Context Contract

## Scope DiddiFreeID

DiddiFreeID owns the `user` resource context only. It does not expose a
module's deliveries, rides, payments, documents, support notes, OTPs or
authentication secrets.

## Endpoint

```http
GET /internal/v1/support/users/{user_id}/context
Authorization: Bearer <service_jwt>
X-Client-ID: diddisupport-staging-diddifreeid
X-Request-ID: <uuid-or-case-correlation-id>
```

The response follows `diddi.context.v1`:

```json
{
  "protocol": "diddi.context.v1",
  "resource_type": "user",
  "resource_id": "5c0e3c6a-8622-41f1-a4a6-b4ebffc8cf2a",
  "context": {
    "display_name": "Awa Koné",
    "phone_masked": "+225******00",
    "email_masked": "a***@example.com",
    "language": "fr",
    "account_status": "active",
    "created_at": "2026-10-20T09:00:00Z",
    "capabilities": [
      {
        "service": "diddisend",
        "type": "courier",
        "access_status": "enabled",
        "operational_status": "ready",
        "status_source": "diddisend",
        "updated_at": "2026-10-20T09:05:00Z"
      }
    ]
  }
}
```

`phone_masked` and `email_masked` are display values, not identifiers that can
be reused for authentication or outreach. DiddiSupport must query the owning
module for any business context.

## Service-to-service authorization

Only the `diddisupport` service can call this route. Its client must be active
in DiddiFreeID with:

```yaml
client_id: diddisupport-staging-diddifreeid
service: diddisupport
environment: staging
audience: diddifree-id
scope: identity:support-context:read
```

Create the client through the existing DiddiFreeID provisioning command:

```bash
python scripts/create_service_client.py \
  --client-id diddisupport-staging-diddifreeid \
  --service diddisupport \
  --environment staging \
  --audience diddifree-id \
  --scope identity:support-context:read
```

The service token lifetime remains `SERVICE_TOKEN_LIFETIME_SECONDS`, currently
600 seconds by default. DiddiSupport must send the exact same client ID in the
token request and in `X-Client-ID` on the context request.

## DiddiSupport calls to business modules

DiddiSupport uses a separate client per target module. These clients authorize
only the matching support-context read scope; they do not authorize writes,
admin operations or access to another module's context.

| Client ID | Audience | Scope |
| --- | --- | --- |
| `diddisupport-staging-diddigo` | `diddigo` | `diddigo:support-context:read` |
| `diddisupport-staging-diddifood` | `diddifood` | `diddifood:support-context:read` |
| `diddisupport-staging-diddisend` | `diddisend` | `diddisend:support-context:read` |
| `diddisupport-staging-diddipay` | `diddipay` | `diddipay:support-context:read` |

Each credential is stored locally in `diddisupport-staging.secrets.env`, which
is ignored by Git through the `*.secrets.env` rule. DiddiSupport obtains a
fresh token from `/identity/v1/auth/service/token` when needed; access tokens
are intentionally not stored in this file.

## Error contract

- `401 TOKEN_MISSING`, `SERVICE_TOKEN_INVALID` or `SERVICE_CLIENT_ID_INVALID`:
  authentication is malformed or inconsistent.
- `403 SERVICE_SUPPORT_CONTEXT_FORBIDDEN`: caller is not DiddiSupport.
- `403 SERVICE_SCOPE_INVALID`: the token lacks `identity:support-context:read`.
- `404 USER_NOT_FOUND`: the user does not exist in DiddiFreeID.
