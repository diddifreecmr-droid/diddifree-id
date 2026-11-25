# ADR-0003: Authentification service-to-service

- Statut: accepted
- Référence Jira: SCRUM-405 (convention commune), SCRUM-415 (ADR)
- Remplace: la convention générale `X-Client-ID` + `X-Service-Key` pour les nouveaux appels

## Décision

Les nouveaux appels backend utilisent un JWT court émis par DiddiFreeID :

```http
Authorization: Bearer <service_jwt>
X-Client-ID: <client_id>
```

Le récepteur vérifie localement la signature avec le JWKS DiddiFreeID, puis
`iss`, `exp`, `aud`, `scope`, `token_type=service`, `status=active` et la
correspondance entre `X-Client-ID` et `client_id`.

`X-Service-Key` reste accepté uniquement pendant la migration des intégrations
existantes. Il n'est pas requis avec un nouveau JWT.

## Clients staging

Pilotage utilise deux clients distincts :

- `pilotage-staging-diddifreeid`: `aud=diddifree-id`, scopes identité ;
- `pilotage-staging-diddigo`: `aud=diddigo`, scope `ride-summary:read`.

DiddiAdmin utilise un client distinct pour DiddiFood :

- `backoffice-staging-diddifood`: `aud=diddifood`, scopes Food explicitement autorisés.

Cette séparation limite les permissions et permet de révoquer une intégration
sans couper l'autre.

## Révocation

Révoquer un client empêche l'émission de nouveaux tokens. Un JWT déjà émis
reste valide jusqu'à `exp`, avec une durée par défaut de 600 secondes. Une
révocation immédiate nécessiterait une introspection ou une denylist distribuée,
hors périmètre V1.
