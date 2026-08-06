# DiddiFreeID

> **Frontière actuelle** : DiddiFreeID gère l'identité, l'authentification, le
> profil global et les statuts de compte. Les rôles métier (`driver`,
> `merchant`, etc.) sont gérés par leurs modules propriétaires, pas par Auth.

Service d'identité central de l'écosystème DiddiFree. Implémentation de
[`DiddiFreeID_Architecture.md`](DiddiFreeID_Architecture.md) et de
[`DiddiFreeID_Contrat_API.md`](DiddiFreeID_Contrat_API.md).

**Stack :** Python 3.11 · FastAPI · PostgreSQL · Redis · JWT RS256 · Alembic

---

## Démarrage

```bash
workon diddicore                      # virtualenv du projet
pip install -e ".[dev]"

docker compose up -d db redis         # Postgres :15438, Redis :16391
python scripts/generate_keys.py       # paire RSA de développement → keys/
cp .env.example .env                  # puis ajuster si besoin

alembic upgrade head
uvicorn identity_app.main:app --reload
```

Documentation interactive : `http://localhost:8000/docs`.

Pour Portainer, utiliser `docker-compose.portainer.yml`. Le compose configure
les URLs internes `db:5432` et `redis:6379`; ne pas injecter des URLs en
`localhost` dans la stack. Au premier démarrage, le conteneur `app` génère les
clés RSA via `scripts/generate_keys.py` dans le volume Docker persistant
`jwtkeys`, puis réutilise ces mêmes clés lors des redémarrages. Aucun fichier de
clé ni script n'est requis sur le VPS. Ne pas supprimer le volume `jwtkeys`,
sinon tous les tokens signés précédemment deviendront invalides. Ce fichier ne
charge pas `.env`.

Les chemins des clés sont fixes dans le conteneur : `/app/keys/private.pem` et
`/app/keys/public.pem`. Ils sont générés automatiquement au premier démarrage
et ne sont pas exposés dans les variables d'environnement de Portainer.

### Bootstrap d'un administrateur

Le premier administrateur se crée depuis la console backend, jamais via une
route HTTP publique. En local :

```bash
python scripts/create_admin.py \
  --phone +2250700000000 \
  --email admin@diddifree.com \
  --name "DiddiFree Admin" \
  --minutes 60
```

Dans Portainer, ouvrir la console du conteneur `app` et exécuter la même
commande. Le script crée l'utilisateur en `role=admin`, `status=active`, puis
affiche une seule fois `admin_token=...`. Le token n'est pas enregistré en
base ni dans Git. Pour promouvoir un utilisateur existant, ajouter
explicitement `--promote-existing`.

Pour les interfaces de test, définir `CORS_ALLOWED_ORIGINS` dans la stack
Portainer avec les origines exactes séparées par des virgules, par exemple
`http://localhost:3000,http://localhost:5173`.

En staging, le transport OTP peut être basculé sur Telegram avec
`OTP_PROVIDER=telegram` et `TELEGRAM_BOT_TOKEN` dans Portainer. L'utilisateur
doit d'abord ouvrir le bot et partager son propre contact; Auth lie alors son
`telegram_chat_id` à son compte et envoie les codes suivants dans ce chat.

L'e-mail est aussi disponible avec `OTP_PROVIDER=email` et les variables SMTP
de Portainer. Une requête peut choisir explicitement `"channel": "email"` ou
`"channel": "telegram"`. Dans les deux cas, `OTP_LOG_PLAINTEXT=true` garde le
code visible dans les logs ; `false` le masque.

Les ports 15438 et 16391 ne sont pas ceux de DiddiGo (5433/6379) ni de
DiddiPay/Fund (5434/6380), pour que les trois stacks tournent en parallèle sur
la même machine — ce qui est exactement la situation pendant la bascule décrite
en §7 de l'architecture.

Le service `app` expose par défaut le port `18010` sur l'hôte. Si Portainer ou
le VPS utilise déjà ce port, il suffit d'override `APP_HOST_PORT` dans
`.env` ou dans la stack.

## Tests

```bash
pytest
```

96 tests. Ils tournent contre le vrai Postgres et le vrai Redis de
`docker-compose`, sur une base `diddi_free_id_test` recréée à chaque session et
migrée par Alembic — les migrations sont donc testées à chaque exécution.

```bash
ruff check .
```

---

## Organisation

```
identity_app/
├── core/                     config, base, Redis, clés RSA, erreurs, dépendances
├── shared_kernel/
│   ├── contracts/            IdentityVerifierPort — le code que les modules importent
│   └── events/               bus Redis Pub/Sub
└── modules/identity/
    ├── presentation/         routers FastAPI + schémas Pydantic
    ├── application/
    │   ├── commands/         écrivent (RegisterUser, VerifyOtp, ChangeStatus…)
    │   └── queries/          lisent (GetUserById, ListUsers, GetJwks…)
    ├── domain/               entités, ports, événements — ne dépend de rien
    └── infra/                write_repository, read_repository, cache, tokens, SMS
```

### Le CQRS léger, concrètement

La séparation n'est pas décorative, elle est visible dans les types : une
commande reçoit un `UserWriteRepository`, une query un `UserReadRepository`, et
`core/deps.py` ne câble jamais l'un à la place de l'autre. Une commande ne peut
donc pas lire le cache par accident, une query ne peut pas écrire.

`tests/test_cqrs_boundaries.py` lit le graphe d'imports et échoue si la
frontière est franchie — parce qu'une discipline de code sans garde-fou se perd
à la première urgence. Les mêmes tests vérifient que `domain/` ne dépend de
rien, la propriété qui rend le module extractable plus tard.

Le déclencheur pour passer en CQRS complet reste celui de l'architecture §1 :
une latence de lecture mesurée, pas supposée. Le jour venu, seule la session
passée à `SqlAlchemyUserReadRepository` change.

### Le KYC chauffeur

La validation KYC quitte DiddiGo, où elle est auto-approuvée, pour venir ici
(architecture §7.5). Le parcours :

1. Ride valide le permis de son côté, puis appelle
   `PATCH /users/{id}/role {"role": "driver", "reason": "…"}`.
2. DiddiFreeID **n'accorde pas** le rôle : il enregistre la demande dans
   `users.requested_role` et publie `user.updated`.
3. Un admin instruit le dossier depuis la file
   `GET /admin/users?pending_kyc=true`, puis tranche avec
   `PATCH /admin/users/{id}/kyc {"approved": true|false, "reason": "…"}`.
4. En cas d'accord, le rôle passe à `driver` et `user.role_changed` part — c'est
   l'événement que Ride attend pour activer ses fonctionnalités chauffeur.

**Une demande ne retire jamais rien.** `status` est global et lu par les 12
modules : si une demande de rôle chauffeur faisait basculer un compte actif en
`pending_kyc`, cette personne perdrait DiddiPay et DiddiShop pendant
l'instruction. Elle conserve donc `role=user` et `status=active`, et seul son
rôle chauffeur est en attente.

`pending_kyc` ne concerne que les comptes **jamais activés** — c'est le
« `pending_kyc` avant `active` » de l'architecture, appliqué là où il ne coûte
rien. Ces comptes peuvent lire `/users/me` et rafraîchir leur token (ils doivent
pouvoir suivre leur dossier), mais tout module refuse d'agir puisque leur
`status` n'est pas `active`. Un refus les rend simplement `active` en tant
qu'utilisateurs ordinaires.

Un admin ne peut pas poser `pending_kyc` à la main
(`422 STATUS_NOT_SETTABLE`) : ce serait exactement le verrouillage
ecosystème-wide décrit plus haut.

Le KYC **documentaire** (upload de pièce) reste hors périmètre, comme le contrat
§5 le prévoit — c'est un sous-module dédié, pas un champ de plus sur `users`.

### Le bus : Redis Streams

Pub/Sub ne persiste pas : un module arrêté au moment de la publication ne voit
jamais l'événement. Sans conséquence pour une invalidation de cache, inacceptable
pour `user.registered` dont dépend la création du compte Wallet.

Les Streams corrigent exactement ça, sur le Redis déjà déployé : les entrées
persistent, chaque module a son consumer group, et une entrée reste *pending*
tant que le module ne l'a pas acquittée — un consommateur qui plante en cours de
traitement la revoit au redémarrage.

`RedisEventConsumer` (dans `shared_kernel/events/bus.py`) est le code que les
modules copient :

```python
consumer = RedisEventConsumer(redis, group="diddi-wallet", name="worker-1")
await consumer.ensure_group(from_beginning=True)

for entry_id, event in await consumer.read_pending():   # ce qui restait en vol
    await handle(event); await consumer.ack(entry_id)

while True:
    for entry_id, event in await consumer.read():
        await handle(event); await consumer.ack(entry_id)
```

Acquitter **après** traitement, jamais avant : c'est l'écart entre les deux qui
transforme un crash en redélivrance plutôt qu'en perte. La contrepartie est que
la livraison est *at-least-once* — les handlers doivent être idempotents.

**Pourquoi pas Kafka.** Kafka règle le même problème et apporte en plus le
partitionnement, une rétention longue et le replay à profondeur arbitraire. Il
apporte aussi un cluster à exploiter, superviser et maintenir en vie. Pour 12
modules dont la plupart ne sont pas écrits, c'est un coût réel face à un problème
que les Streams résolvent déjà. Le jour où le volume, l'ordonnancement inter-
partitions ou le replay de plusieurs mois comptent, seul `bus.py` change — le
reste du service ignore quel transport est dessous.

### La réconciliation

Elle n'est pas une alternative au broker, elle le complète : la rétention du
stream est bornée (`STREAM_MAX_LEN`), et surtout un écrit peut réussir alors que
la publication échoue — aucun transport ne ferme cet écart tout seul.

```
GET /users/backfill?since=2026-07-01T00:00:00Z&page=1&page_size=100
```

Authentification service-à-service, comptes rendus du plus ancien au plus
récent pour qu'un parcours interrompu reprenne au dernier `created_at` vu. À
appeler au démarrage par un module nouveau, ou absent au-delà de la fenêtre de
rétention. La consommation doit être idempotente : le module reverra
nécessairement des comptes qu'il connaît déjà.

### Vérification locale des tokens

`identity_app/shared_kernel/contracts/identity_provider.py` est le fichier à
copier dans Wallet, Fund, Ride, Shop. Il ne dépend que de `httpx` et `pyjwt` —
un test le vérifie, pour qu'il reste copiable.

```python
verifier = JwksIdentityVerifier("https://api-dev.diddifree.app/identity/v1")
identity = await verifier.verify(bearer_token)   # aucun appel réseau après le 1er
```

`tests/test_jwks_verification.py` compte les requêtes HTTP : une seule, pour
charger le JWKS. Les 20 vérifications suivantes n'en font aucune. C'est l'étape 3
des « prochaines étapes » de l'architecture, tenue et mesurée.

### Rotation de clé

```bash
python scripts/generate_keys.py --out keys/next --kid 2026-10-01
```

Puis dans `.env` : `JWT_PRIVATE_KEY_PATH` et `JWT_ACTIVE_KID` pointent sur la
nouvelle paire, `JWT_PREVIOUS_PUBLIC_KEY_PATH` et `JWT_PREVIOUS_KID` sur
l'ancienne clé publique. Les deux sont alors publiées par JWKS et les tokens
émis avant le switch continuent de se vérifier jusqu'à expiration. Redémarrage
requis : le trousseau est chargé au démarrage, volontairement — deux processus
en désaccord sur la clé active seraient bien plus pénibles à diagnostiquer qu'un
rolling restart.

Renseigner un seul des deux champs `PREVIOUS_*` fait échouer le démarrage, plutôt
que de casser silencieusement la vérification.

### Migration depuis DiddiGo

```bash
python scripts/migrate_from_diddigo.py --dry-run
python scripts/migrate_from_diddigo.py
```

Les `id` sont conservés — `ride.rides.passenger_id` et `driver_profiles` les
référencent déjà. Le rôle `passenger` devient `user` ; tout rôle ou statut non
reconnu arrête la migration du compte concerné au lieu d'être deviné. Un
téléphone déjà pris par un autre `id` est signalé pour arbitrage, jamais écrasé.
Le script est idempotent.

---

## Écarts et points ouverts

Ce qui a été tranché en implémentant, et qui mérite d'être validé.

### Décisions prises sur des points que les documents laissent ouverts

| Point | Décision | Pourquoi |
|---|---|---|
| Auth service-à-service (contrat §5, « à trancher ») | Les deux formes sont implémentées : en-tête `X-Service-Key` (`SERVICE_API_KEYS`) et token `role=service` (`scripts/issue_service_token.py`) | Le choix dépend du modèle réseau retenu avec l'équipe Infra. Livrer les deux évite de bloquer les modules en attendant, et l'une se désactive par configuration |
| `PATCH /users/{id}/role` | Ouvert aux services **et** aux admins | Le contrat le range en §3 « réservé `role=admin` » mais son texte dit qu'un module backend l'appelle. Les deux lectures sont satisfaites |
| `POST /auth/otp/verify` sur un numéro sans compte | `404 USER_NOT_FOUND` | La création de compte appartient à `/auth/register`. En créer un ici contournerait le `409` sur doublon et produirait des comptes sans `full_name` |
| `POST /auth/otp/request` sur un numéro inconnu | `200`, identique à un numéro connu, cooldown armé quand même | Toute différence transforme la route en oracle « cette personne est-elle chez DiddiFree » |
| Réutilisation d'un refresh token déjà tourné | `401` **et** révocation de toutes les sessions de l'utilisateur | Fuite et retry client sont indistinguables ici ; réémettre donnerait une vie illimitée à un token volé |
| Hachage des codes OTP | HMAC-SHA256 avec un poivre serveur, pas un SHA-256 nu | Un code à 6 chiffres a un million de valeurs : un hash nu se renverse instantanément à partir d'un dump. Le poivre vit en configuration, pas en base |
| Suspension d'un compte | Révoque immédiatement tous ses refresh tokens | Sinon la suspension n'agit qu'au bout des 15 min du JWT courant |
| Statuts | Machine à états explicite ; `active → pending_verification` et `active → pending_kyc` interdits | Renvoyer un compte vivant en « non vérifié » le priverait d'authentification sans trace d'audit lisible ; et `pending_kyc` sur un compte actif le couperait des 12 modules pour la revue d'un seul |
| KYC (archi §7.5) | `PATCH /users/{id}/role` vers `driver`/`merchant` **demande** le rôle au lieu de l'accorder ; décision par `PATCH /admin/users/{id}/kyc` | Le portillon quitte DiddiGo comme demandé, sans qu'une demande ne dégrade un compte qui fonctionne |
| Transport du bus (contrat §4, « à documenter ») | Redis Streams, avec consumer groups et ACK | Résout la non-persistance sur l'infra déjà en place ; Kafka reste la destination quand le volume ou le replay long le justifieront |

### Ajouts par rapport aux documents

- `PATCH /users/me` — `UpdateProfile` figure dans l'architecture §2 et
  `user.updated` en §6, mais aucune route ne les exerçait dans le contrat.
- `PATCH /admin/users/{id}/kyc` et le filtre `?pending_kyc=true`, sans lesquels
  le statut `pending_kyc` serait un cul-de-sac.
- `GET /users/backfill` — rattrapage pour un module nouveau ou absent au-delà de
  la rétention du stream.
- Table `identity.user_role_history` et colonne `users.requested_role`. La
  première comble un vrai trou : le `reason` documenté sur
  `PATCH /users/{id}/role` était accepté puis **jeté**, ce qui rendait l'exemple
  du contrat lui-même (« Validation KYC chauffeur DiddiGo, dossier #4021 »)
  illisible après coup.
- Champ `requested_role` dans le profil publié — additif, sans impact pour un
  consommateur qui lit les champs documentés.
- Index `idx_refresh_token_hash` — absent du SQL de §4, alors que chaque refresh
  et chaque logout cherchent un token par son hash et rien d'autre.
- Limite `page_size ≤ 100` sur `GET /admin/users`.
- `/health`, et JWKS monté à la racine **et** sous le préfixe (le contrat le
  documente sous `/identity/v1`, la RFC 8615 le place à la racine).

### Incohérences relevées dans les documents

1. **`410` absent du tableau des codes HTTP** (contrat §0) alors que §1 le
   spécifie pour `OTP_EXPIRED`. Le comportement de §1 est bien celui
   implémenté ; seul le tableau récapitulatif gagnerait à être complété (`410`,
   et `403 USER_SUSPENDED`).
2. **`user.role_changed` n'apparaît pas dans le tableau des événements de
   l'architecture §6** mais figure bien dans le contrat §4. Implémenté.
3. **Le statut `pending_kyc`** est évoqué en architecture §7.5 mais absent du
   schéma de §4. Ajouté (voir « Le KYC chauffeur » plus haut) — le schéma de §4
   est donc à mettre à jour avec `requested_role` et `user_role_history`.

### Limites assumées

- **La livraison des événements est *at-least-once*, pas *exactly-once*.** Un
  consommateur qui plante entre le traitement et l'`ack` reverra l'événement :
  les handlers doivent être idempotents. Aucun broker, Kafka compris, ne change
  ça sans coopération du handler.
- **La rétention du stream est bornée** et un écrit peut réussir alors que la
  publication échoue. `GET /users/backfill` est le filet pour les deux cas.
- **Envoi SMS non branché** — le code OTP est journalisé (`OTP_LOG_PLAINTEXT`,
  à couper en production). Le port existe, l'agrégateur reste à choisir.
- **Authentification par mot de passe non exposée** — Argon2id est en place
  (`core/security.py`) et la colonne existe, mais aucune route ne l'utilise :
  le contrat §5 la range explicitement dans le « pas encore ».
- **Rôle unique par utilisateur**, conformément au modèle actuel. Un utilisateur
  à la fois `driver` et `merchant` demandera une table de liaison.
- **`GET /users/{id}` sert le cache Redis**, comme toute query. Un module qui
  lit un profil juste après l'avoir modifié via une autre route verra la
  nouvelle valeur (les commandes invalident), mais un profil modifié
  directement en base hors application resterait en cache jusqu'à 5 minutes.
