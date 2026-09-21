# DiddiFreeID Service Token

## Endpoint

`POST /identity/v1/auth/service/token`

Content type: `application/x-www-form-urlencoded`.

Required fields:

- `grant_type=client_credentials`
- `client_id`
- `client_secret`
- `audience` — service cible enregistré pour ce client, par exemple `diddifree-id`, `diddigo` ou `diddifood`
- `scope` — scopes séparés par des espaces

Example:

```bash
curl -X POST https://auth-staging.diddifree.com/identity/v1/auth/service/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'X-Client-ID: pilotage-staging-diddifreeid' \
  --data-urlencode 'grant_type=client_credentials' \
  --data-urlencode 'client_id=pilotage-staging-diddifreeid' \
  --data-urlencode 'client_secret=SECRET_STOCKE_DANS_PORTAINER' \
  --data-urlencode 'audience=diddifree-id' \
  --data-urlencode 'scope=profile:read'
```

Response: `access_token`, `token_type`, `expires_in`, `scope`.

## Claims

The JWT is signed with the existing DiddiFreeID RS256 key and contains:

- `iss=diddifree-id`
- `sub=service:<service_name>`
- `role=service`, `status=active`, `token_type=service`
- `client_id`, `service`, `aud`, `scope`, `jti`, `iat`, `exp`

Default lifetime is 600 seconds and is configured with
`SERVICE_TOKEN_LIFETIME_SECONDS`.

## Provisioning

Create one client per target service from the DiddiFreeID container or local
checkout. For DiddiFreeID:

```bash
python scripts/create_service_client.py \
  --client-id pilotage-staging-diddifreeid \
  --service pilotage \
  --environment staging \
  --audience diddifree-id \
  --scope profile:read \
  --scope role:write \
  --scope users:backfill:read
```

For Radar DG calls to DiddiGo:

```bash
python scripts/create_service_client.py \
  --client-id pilotage-staging-diddigo \
  --service pilotage \
  --environment staging \
  --audience diddigo \
  --scope ride-summary:read
```

For DiddiAdmin calls to DiddiFood:

```bash
python scripts/create_service_client.py \
  --client-id backoffice-staging-diddifood \
  --service backoffice \
  --environment staging \
  --audience diddifood \
  --scope food:restaurants:read \
  --scope food:restaurants:write
```

For DiddiBackoffice calls to DiddiFreeID:

```bash
python scripts/create_service_client.py \
  --client-id backoffice-staging-diddifreeid \
  --service backoffice \
  --environment staging \
  --audience diddifree-id \
  --scope capabilities:read \
  --scope capabilities:access:write
```

The secret is displayed once. Store it in the consuming service's Portainer
environment and do not commit it. New backend calls use both headers:

```http
Authorization: Bearer <service_jwt>
X-Client-ID: <client_id>
```

The receiver verifies that `X-Client-ID` matches the JWT `client_id` claim and
that `aud` and `scope` authorize the requested operation. Existing
`X-Service-Key` and manually issued `role=service` tokens remain compatible
only during the migration window; `X-Service-Key` is not required with a new
JWT. New tokens use:

- `GET /users/{user_id}`: `profile:read`
- `GET /users/backfill`: `users:backfill:read`
- `PATCH /users/{user_id}/role`: `role:write`
- `PATCH /pro/internal/users/{user_id}/capabilities/{service}/{type}/status`: `capabilities:write`
- `GET /admin/users/{user_id}/capabilities`: `capabilities:read` for the Backoffice service
- `PATCH /admin/users/{user_id}/capabilities/{service}/{type}`: `capabilities:access:write` for the Backoffice service
