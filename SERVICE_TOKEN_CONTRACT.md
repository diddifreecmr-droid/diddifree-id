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

Pour le reporting d'identité consommé par Pilotage, le scope dédié est
`identity:reporting:read`. Il ne donne pas accès aux profils individuels ni aux
routes Backoffice.

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

For Pilotage's aggregate identity summary:

```bash
python scripts/create_service_client.py \
  --client-id pilotage-staging-diddifreeid \
  --service pilotage \
  --environment staging \
  --audience diddifree-id \
  --scope identity:reporting:read
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
- `GET /internal/pilotage/identity-summary?date=YYYY-MM-DD`: `identity:reporting:read` for Pilotage

The identity summary is an aggregate response only. It contains the total
number of users, users registered on the requested day, verified users, active
users, authenticated DAU and authenticated month-to-date MAU. DAU/MAU are based
on successful OTP verification and refresh-token activity, deduplicated by user
and business day in the `Africa/Abidjan` timezone. It does not expose user IDs,
phone numbers, emails, documents, or business-module data.

## Gestion des clients S2S

Un administrateur humain peut consulter et modifier la politique d'un client
S2S sans jamais voir son secret en clair:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://auth-staging.diddifree.com/identity/v1/admin/service-clients

curl -X PATCH \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://auth-staging.diddifree.com/identity/v1/admin/service-clients/backoffice-staging-diddigo \
  -d '{"allowed_audiences":["diddigo"],"allowed_scopes":["ride-summary:read","diddigo:drivers:read"]}'
```

Le même endpoint accepte `{"active":false}` pour révoquer un client et
`{"active":true}` pour le réactiver. Une révocation empêche immédiatement
l'émission de nouveaux jetons; les jetons déjà émis restent valides jusqu'à
leur expiration courte, actuellement 600 secondes. Les réponses ne
contiennent ni `secret_hash` ni `client_secret`.

Les scopes sont définis par le service cible. DiddiFreeID les autorise ou les
refuse pour le client, tandis que DiddiGo, DiddiPay, DiddiFiles ou DiddiFood
doivent vérifier l'audience et le scope requis sur chacune de leurs routes.
