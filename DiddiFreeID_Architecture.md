# DiddiFreeID — Architecture applicative & Conception

**Stack retenue :** Python / FastAPI · PostgreSQL · Redis · JWT (RS256)
**Périmètre :** service d'identité central de l'écosystème DiddiFree — remplace à terme les modules
`auth` internes construits par les équipes produit (DiddiGo notamment).
**Version : 1.0** — 2026-07-29
**Statut :** Implémenté. Le code de ce dépôt suit ce document ; les écarts assumés sont listés dans le
`README.md`.
**Historique :**
- *Design* — document de conception, avant implémentation.
- **v1.0 (2026-07-29)** — première version livrée. Les décisions prises pendant l'implémentation, et les
  ajouts par rapport au design initial (portillon KYC dans le schéma, bus arrêté sur Redis Streams, audit
  des changements de rôle, index et colonnes), sont signalés par « **Implémentation :** ».
- *v2 — à venir.* Les questions restées ouvertes sont regroupées en section 10.

**Document miroir :** `DiddiFreeID_Contrat_API.md` (destiné aux équipes consommatrices : Wallet, Fund, Ride, etc.)

---

> **Mise à jour d'architecture (2026-08-04)** : l'authentification et le
> profil sont centraux, mais les rôles métier restent dans les modules qui les
> définissent. Auth ne crée plus de rôle `driver` ou `merchant` ; ces anciennes
> valeurs restent lisibles uniquement pour permettre une migration progressive.

## 0. Rôle dans l'écosystème

Le cahier des charges pose DiddiFree ID comme le socle transverse :

> Identité unique DiddiFree ID : authentification centralisée, profil unique partagé par tous les modules.

DiddiFreeID n'est **pas** un module métier comme DiddiPay ou DiddiFund — c'est une fondation. Sa
particularité, et ce qui va guider toute l'architecture ci-dessous, est un profil de charge très
asymétrique : **très peu d'écritures, énormément de lectures/vérifications**, sollicitées en permanence
par les 12 modules à chaque requête utilisateur.

C'est ce déséquilibre qui justifie qu'on en discute sous l'angle CQRS — mais pas n'importe quelle version
du CQRS. Voir section 1.

---

## 1. CQRS — quel niveau, et pourquoi

### Le vrai problème de charge n'est pas où on l'imagine

Si chaque requête de chaque module (un paiement DiddiPay, une commande DiddiGo, un achat DiddiShop...)
devait appeler DiddiFreeID en HTTP pour vérifier le token de l'utilisateur, ce service deviendrait très
vite le goulot d'étranglement de tout l'écosystème — un point de défaillance unique consulté des dizaines
de milliers de fois par jour rien que pour du Pay/Fund, et bien davantage une fois les 12 modules actifs.

**La première décision d'architecture, avant même de parler CQRS, est donc : la vérification d'un token
ne doit jamais nécessiter d'appel réseau vers DiddiFreeID.** On utilise du JWT signé en **RS256**
(clé privée chez DiddiFreeID, clé publique distribuée via un endpoint JWKS) : chaque module vérifie la
signature localement, avec la clé publique mise en cache. DiddiFreeID n'est donc appelé en réalité que
pour :

- Émettre un token (inscription, connexion, refresh).
- Des requêtes ponctuelles côté admin/back-office (lister des utilisateurs, suspendre un compte).
- La récupération de profil complet quand un module a besoin de plus que ce que le JWT transporte déjà
  (le JWT porte `user_id`, `role`, `status` — suffisant pour l'autorisation ; pas `full_name` ou d'autres
  détails de profil).

Une fois ce point posé, le volume de requêtes *réellement* servies par DiddiFreeID lui-même redevient
raisonnable — de l'ordre de l'inscription/connexion/refresh de chaque utilisateur, pas de chaque
transaction de chaque module.

**Implémentation :** cette promesse est désormais mesurée, pas seulement affirmée. `tests/test_jwks_verification.py`
compte les requêtes HTTP d'un module consommateur : **une seule**, pour charger le JWKS ; les vingt
vérifications suivantes n'en produisent aucune.

### Donc : CQRS léger, pas CQRS complet

| | CQRS complet (event sourcing, bases lecture/écriture séparées) | CQRS léger (séparation dans le code, une seule base) |
|---|---|---|
| Quand c'est justifié | Écritures et lectures avec des besoins de scalabilité radicalement différents, à des volumes très élevés des deux côtés | Charge de lecture plus élevée que l'écriture, mais pas au point de saturer une base relationnelle bien indexée |
| Coût | Complexité de synchronisation lecture/écriture (latence de projection), infra doublée, debug plus dur | Quasi nul — c'est une discipline de code, pas une infra en plus |
| Notre cas | Non — grâce à la vérification JWT locale, DiddiFreeID lui-même n'encaisse pas un volume extrême | **Oui** |

**Décision : CQRS léger.** On sépare strictement, dans le code, les **commandes** (qui modifient l'état :
`RegisterUser`, `VerifyOtp`, `RefreshToken`, `UpdateProfile`, `SuspendUser`) des **requêtes** (qui lisent
sans modifier : `GetUserById`, `GetUserByPhone`, `ListUsers`, `GetCurrentUserProfile`), chacune avec son
propre modèle optimisé pour son usage — mais sur **une seule base PostgreSQL**. Un cache Redis vient
absorber les lectures répétées (profil utilisateur, JWKS) sans dupliquer la base.

Si un jour le volume de lecture explose vraiment (ex. un module fait des dizaines de milliers de
`GetUserById` par minute au lieu de se contenter du JWT), on introduira une base de lecture répliquée
(read replica PostgreSQL) — mais ce n'est pas une réécriture, juste un changement d'implémentation dans
la couche `infra` des queries, exactement comme le principe d'extraction qu'on applique partout ailleurs
dans l'écosystème.

**Déclencheur explicite pour passer en CQRS complet** : le jour où la latence des requêtes de lecture
devient un problème mesuré (pas supposé) malgré le cache Redis et les index, ou le jour où on veut
reconstruire un historique complet des changements d'un utilisateur (event sourcing) pour de l'audit
réglementaire poussé — pas avant.

**Implémentation — comment la discipline tient dans le temps.** Une séparation qui n'existe que dans les intentions
se perd à la première urgence. Deux mécanismes la maintiennent :

1. **Elle est visible dans les types.** Une commande reçoit un `UserWriteRepository`, une query un
   `UserReadRepository`, et `core/deps.py` ne câble jamais l'un à la place de l'autre. Une commande ne
   *peut pas* lire le cache par accident.
2. **Elle est vérifiée par les tests.** `tests/test_cqrs_boundaries.py` lit le graphe d'imports et échoue
   si une query touche le côté écriture, si une commande passe par le dépôt de lecture, ou si le `domain`
   se met à dépendre d'une techno ou d'une couche extérieure.

---

## 2. Architecture applicative — organisation en modules verticaux

Même principe que pour Wallet/Fund et DiddiGo : monolithe modulaire, 4 couches, extraction possible plus
tard sans réécriture. La différence ici : la couche `application` est elle-même scindée en `commands/` et
`queries/`.

**Implémentation :** l'arborescence ci-dessous est celle du code livré.

```
identity_app/
├── core/                          # config, DB engine, sécurité, clés RSA
│   ├── settings.py
│   ├── database.py
│   ├── redis.py
│   ├── keys.py                    # chargement clé privée (signature) / publique (JWKS), rotation
│   ├── security.py                # hachage OTP (HMAC+poivre) et mots de passe (Argon2id)
│   ├── errors.py                  # enveloppe d'erreur commune à l'écosystème
│   ├── deps.py                    # injection de dépendances — le seul point de câblage
│   ├── auth_deps.py               # dépendances d'authentification et d'autorisation
│   └── lifespan.py
│
├── shared_kernel/
│   ├── contracts/                 # interfaces exposées aux autres modules de l'écosystème
│   │   └── identity_provider.py   # IdentityVerifierPort + JwksIdentityVerifier, côté CONSOMMATEUR
│   └── events/
│       └── bus.py                 # publication et consommation — Redis Streams
│
├── modules/
│   └── identity/                  # ── Module unique DiddiFreeID ──
│       ├── presentation/          # routers FastAPI (auth, users, admin, jwks), schémas Pydantic
│       │
│       ├── application/
│       │   ├── commands/          # RegisterUser, RequestOtp, VerifyOtp, RefreshAccessToken, Logout,
│       │   │                      # UpdateProfile, ChangeRole, DecideKyc, ChangeStatus
│       │   ├── queries/           # GetUserById, GetUserByPhone, GetCurrentUserProfile, ListUsers, GetJwks
│       │   ├── payloads.py        # forme publiée d'un utilisateur — partagée, appartenant à aucun des deux côtés
│       │   └── validation.py      # règles d'entrée communes (format E.164)
│       │
│       ├── domain/                # entités : User, OtpCode, RefreshToken, historiques — aucune dépendance technique
│       │   └── events/            # définitions des événements de domaine
│       │
│       └── infra/
│           ├── models.py              # tables SQLAlchemy du schéma `identity`
│           ├── write_repository.py    # écritures normalisées (PostgreSQL, transactionnel)
│           ├── read_repository.py     # lectures — mêmes tables au départ, requêtes optimisées séparément
│           ├── cache.py               # Redis : profils fréquemment lus
│           ├── rate_limiter.py        # Redis : compteurs OTP par téléphone et par IP
│           ├── token_service.py       # signature/vérification RS256, gestion JWKS, refresh opaques
│           └── sms_adapter.py         # envoi OTP (agrégateur SMS)
│
└── main.py
```

`payloads.py` mérite un mot : commandes et queries renvoient toutes les deux un profil, et elles doivent
renvoyer **le même**. Le placer dans l'une des deux aurait obligé l'autre à l'importer — précisément le
couplage que la séparation existe pour empêcher.

**Règle de dépendance inchangée** : `presentation → application (commands|queries) → domain ← infra`.
Le `domain` ne dépend de rien. Les `commands` et `queries` dépendent toutes deux du `domain`, mais
n'interagissent jamais entre elles directement — une query ne déclenche jamais une commande, et
inversement.

**Ce qui différencie une commande d'une requête ici, concrètement :**

| | Commande | Requête |
|---|---|---|
| Modifie l'état | Oui | Non |
| Passe par le `write_repository` (transactionnel, cohérence forte) | Oui | Non |
| Peut lire depuis le cache Redis | Non (toujours lecture fraîche avant écriture) | Oui, en priorité |
| Invalide le cache des utilisateurs touchés | Oui | Sans objet |
| Émet des événements de domaine | Oui (`user.registered`, etc.) | Non |
| Exemple | `VerifyOtp` → crée la session, émet `user.registered` si première connexion | `GetCurrentUserProfile` → lit le cache, sinon la base, sans jamais écrire |

**Implémentation — pourquoi les commandes invalident le cache au lieu de le rafraîchir.** Une entrée absente est
toujours sûre : le prochain lecteur la recharge depuis PostgreSQL. Une entrée rafraîchie de travers ne
l'est pas.

---

## 3. Vue d'ensemble runtime

| Composant | Rôle | Techno |
|---|---|---|
| `identity` (commands) | Inscription, OTP, émission/refresh de tokens, décisions KYC, administration | FastAPI + PostgreSQL (écriture) |
| `identity` (queries) | Lecture de profil, listes admin, rattrapage (`backfill`) | FastAPI + PostgreSQL (lecture) + cache Redis |
| Redis | Trois usages distincts : cache profils, compteurs de rate-limiting OTP, et flux d'événements (Streams) | Redis |
| Modules consommateurs (Wallet, Fund, Ride, Shop...) | Vérifient le JWT **localement** via la clé publique JWKS mise en cache — n'appellent DiddiFreeID que pour rafraîchir le cache JWKS (rare, les clés tournent peu souvent) | — |

Le JWKS n'est pas mis en cache dans Redis : il est servi depuis le trousseau chargé en mémoire au
démarrage. L'endpoint continue donc de répondre pendant un incident PostgreSQL **ou** Redis — ce qui est
exactement le moment où l'on tient à ce que la vérification des tokens ne bouge pas.

---

## 4. Schéma de données

**Implémentation :** ajout de `users.requested_role`, de la table `identity.user_role_history`, du statut
`pending_kyc` et de l'index `idx_refresh_token_hash`. Le SQL ci-dessous est celui produit par les
migrations Alembic `a1b2c3d4e5f6` et `b2c3d4e5f6a7`.

```sql
CREATE SCHEMA IF NOT EXISTS identity;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE identity.users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone           VARCHAR(20) NOT NULL UNIQUE,
    full_name       VARCHAR(120),
    password_hash   TEXT,                          -- NULL si l'utilisateur n'utilise que l'OTP
    role            VARCHAR(20) NOT NULL DEFAULT 'user',   -- user | driver | merchant | admin (extensible par module)
    status          VARCHAR(20) NOT NULL DEFAULT 'pending_verification',
                                                   -- pending_verification | pending_kyc | active | suspended
    requested_role  VARCHAR(20),                   -- rôle demandé, en attente de décision KYC ; NULL = rien en cours
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_phone ON identity.users(phone);
CREATE INDEX idx_users_role ON identity.users(role);   -- pour les queries admin type ListUsers filtré par rôle

CREATE TABLE identity.otp_codes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    phone       VARCHAR(20) NOT NULL,
    code_hash   TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    attempts    SMALLINT NOT NULL DEFAULT 0,        -- limite les tentatives de brute-force sur le code
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_otp_phone ON identity.otp_codes(phone);

CREATE TABLE identity.refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL,                      -- jamais le token en clair en base
    device_info VARCHAR(200),
    revoked_at  TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_user ON identity.refresh_tokens(user_id);
-- Chaque refresh et chaque logout cherchent un token par son hash et rien d'autre.
-- Sans cet index, c'est un parcours séquentiel sur la table qui grossit le plus vite du schéma.
CREATE INDEX idx_refresh_token_hash ON identity.refresh_tokens(token_hash);

-- Table d'audit — reprend le principe ride_status_history de DiddiGo
CREATE TABLE identity.user_status_history (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
    from_status VARCHAR(30),
    to_status   VARCHAR(30) NOT NULL,
    reason      TEXT,
    changed_by  UUID,                                -- NULL si automatique, sinon admin_id
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit des décisions de rôle.
-- Le `reason` documenté sur PATCH /users/{id}/role était accepté puis perdu : l'exemple du contrat
-- lui-même (« Validation KYC chauffeur DiddiGo, dossier #4021 ») était illisible six mois plus tard.
CREATE TABLE identity.user_role_history (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id        UUID NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
    from_role      VARCHAR(20),
    to_role        VARCHAR(20),                      -- NULL = refus : la décision a eu lieu, aucun rôle accordé
    requested_role VARCHAR(20),
    reason         TEXT,
    changed_by     UUID,                             -- NULL si un module a agi, sinon l'admin décisionnaire
    changed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_role_history_user ON identity.user_role_history(user_id);
```

**Pourquoi `role` reste une simple colonne texte et non une table de permissions complexe** : à ce stade,
chaque module gère ses propres autorisations fines en interne (ex. DiddiFund décide qui peut créer une
campagne). DiddiFreeID ne fait que dire *qui est l'utilisateur* et *son rôle global* — pas *ce qu'il a le
droit de faire dans chaque module*. Mélanger les deux ferait de DiddiFreeID un point de couplage fort
avec la logique métier de chaque module, ce qu'on veut justement éviter.

### Machine à états des statuts

```
pending_verification ──(OTP vérifié)────────────────────────────────► active
          │                                                             │
          └──(OTP vérifié, mais un rôle KYC est demandé)──► pending_kyc ┘
                                                                 (décision KYC)

active ◄──────────────(réactivation admin)──────────────► suspended
pending_kyc ──────────(suspension admin)────────────────► suspended
```

Deux transitions sont **volontairement absentes** :

- `active → pending_verification` : renvoyer un compte vivant en « non vérifié » le priverait de toute
  authentification sans trace d'audit lisible. La suspension est l'outil prévu pour ça.
- `active → pending_kyc` : voir la section 4 bis. C'est la décision de conception la plus importante de
  la v1.0.

Toute transition hors de ce graphe répond `409 INVALID_STATUS_TRANSITION`.

---

## 4 bis. Le portillon KYC

Le point 5 de la section 7 demandait de resituer la validation KYC chauffeur, aujourd'hui auto-approuvée
dans DiddiGo, du côté de DiddiFreeID. C'est fait, mais pas littéralement — et l'écart mérite d'être
expliqué, parce qu'il porte sur la contrainte la plus structurante du service.

**Le problème : `status` est global.** Il est lu par les 12 modules, à chaque requête, depuis le JWT. Si
une demande de rôle chauffeur faisait basculer un compte déjà actif en `pending_kyc`, cette personne
perdrait l'accès à DiddiPay, DiddiShop et tout le reste pendant l'instruction de son dossier. Un module
imposerait alors sa logique métier à tous les autres — exactement le couplage que la section 4 rejette.

**La règle retenue : une demande de rôle ne retire jamais rien.**

1. Un module (Ride) valide sa propre qualification, puis appelle
   `PATCH /users/{id}/role {"role": "driver", "reason": "..."}`.
2. DiddiFreeID **n'accorde pas** le rôle. Il enregistre la demande dans `users.requested_role`, écrit une
   ligne dans `user_role_history` (avec `to_role = NULL` : rien n'est accordé) et publie `user.updated`.
   Le compte garde son `role` et son `status`.
3. Un administrateur instruit la file `GET /admin/users?pending_kyc=true` et tranche via
   `PATCH /admin/users/{id}/kyc`.
4. En cas d'accord, le rôle change et `user.role_changed` part — c'est cet événement que Ride attend pour
   activer ses fonctionnalités chauffeur. En cas de refus, `to_role` reste `NULL` dans l'audit et le
   compte demeure un utilisateur ordinaire.

**Où `pending_kyc` s'applique donc réellement** : uniquement aux comptes **jamais activés**. Un compte
créé, dont un rôle KYC est demandé avant sa première vérification OTP, part en `pending_kyc` au lieu
d'`active` — c'est le « `pending_kyc` avant `active` » de la section 7, appliqué là où il ne coûte rien
puisque le compte n'avait encore aucun accès.

Ces comptes peuvent lire `/users/me` et rafraîchir leur token — leur propriétaire doit pouvoir ouvrir
l'application et voir où en est son dossier. Mais leur JWT porte `status: pending_kyc`, et tout module
refuse d'agir sur un statut différent d'`active`.

Enfin, un administrateur ne peut **pas** poser `pending_kyc` à la main via la route de statut
(`422 STATUS_NOT_SETTABLE`) : ce serait rétablir par une autre porte le verrouillage transverse que tout
ce qui précède cherche à éviter.

Le KYC **documentaire** (upload de pièce d'identité) reste hors périmètre, conformément à la section 5 du
contrat : c'est un sous-module dédié, pas un champ de plus sur `users`.

---

## 5. JWT & vérification locale — le mécanisme clé

- **Algorithme : RS256** (asymétrique), pas HS256. Avec HS256, tous les modules devraient partager le
  même secret — un module compromis pourrait forger des tokens pour n'importe quel utilisateur. Avec
  RS256, seul DiddiFreeID détient la clé privée (signature) ; les modules n'ont que la clé publique
  (vérification uniquement).
- **Endpoint JWKS** (`GET /.well-known/jwks.json`) : expose la clé publique courante, standard (format
  JWK). Chaque module la récupère au démarrage et la garde en cache local (rafraîchie périodiquement,
  ex. toutes les heures, ou immédiatement si la vérification échoue avec un `kid` inconnu — signe d'une
  rotation de clé).
- **Rotation de clé** : prévoir dès le départ deux clés valides simultanément (`kid` dans le header JWT)
  pour permettre une rotation sans invalider tous les tokens en circulation au moment du switch.
- **Contenu du JWT (`access_token`)** : `sub` (user_id), `role`, `status`, `iss`, `iat`, `exp` (15 min,
  comme DiddiGo). Volontairement minimal — pas de `full_name` ni de données métier, pour ne pas avoir à
  réémettre un token à chaque modification de profil.
- **`refresh_token`** : opaque (pas un JWT), stocké haché en base (`identity.refresh_tokens`), permet la
  révocation immédiate (déconnexion à distance, compte suspendu) — ce qu'un JWT pur ne permet pas avant
  expiration.

**Implémentation — précisions issues de l'implémentation :**

- Une rotation à moitié configurée (clé précédente renseignée sans son `kid`, ou l'inverse) **fait échouer
  le démarrage** plutôt que de casser silencieusement la vérification d'une partie des tokens.
- Le trousseau est chargé une fois au démarrage. Une rotation est donc un changement de configuration
  suivi d'un redémarrage progressif, et non un rechargement à chaud : deux processus en désaccord sur la
  clé active seraient bien plus pénibles à diagnostiquer.
- **DiddiFreeID vérifie ses propres tokens exactement comme les modules** — par `kid`, contre le jeu de
  clés publié. Toute divergence entre ce chemin et celui d'un consommateur se manifesterait par un
  « ça marche ici, pas là-bas », la pire classe de bug à diagnostiquer entre douze équipes.
- Le code que les modules intègrent est fourni : `shared_kernel/contracts/identity_provider.py`. Il ne
  dépend que de `httpx` et `pyjwt`, ce qu'un test vérifie — sinon il cesserait d'être copiable et chaque
  consommateur hériterait des dépendances internes de ce service.

---

## 6. Événements de domaine — comment les modules réagissent aux changements d'identité

DiddiFreeID publie sur le bus interne (`shared_kernel/events`) :

| Événement | Émis quand | Consommé par |
|---|---|---|
| `user.registered` | Première vérification OTP réussie | Wallet (création automatique du compte), Fund, Skill (création de profil) |
| `user.updated` | Changement de `full_name`, demande ou refus de rôle KYC, réactivation d'un compte | Tous les modules qui mettent en cache des données de profil |
| `user.role_changed` | Rôle effectivement accordé (ex. `user` → `driver` après décision KYC favorable) | Ride, Skill |
| `user.suspended` | Admin suspend un compte | Wallet (gel des transactions), Ride (désactivation chauffeur), etc. |

Ce point est important pour Wallet en particulier : plutôt que Wallet interroge DiddiFreeID à chaque
inscription pour savoir "est-ce que ce user existe", il **écoute** `user.registered` et crée
automatiquement le compte wallet correspondant. Cohérent avec le flux de données déjà décrit dans le
cahier des charges (DiddiPay → tous les modules) mais dans l'autre sens ici (identité → tous les modules).

**Implémentation — pourquoi il n'y a que ces quatre noms.** Deux situations auraient pu en justifier de nouveaux : la
réactivation d'un compte, et l'ouverture d'un dossier KYC. Les deux passent par `user.updated`. Inventer
`user.reactivated` ou `user.kyc_requested` reviendrait à publier des événements auxquels personne
n'est abonné, c'est-à-dire des notifications silencieusement perdues. Ce que ces deux cas ont réellement
besoin de dire, c'est « votre copie du profil est périmée » — ce qu'`user.updated` signifie déjà.

### Le transport : Redis Streams

Le choix était laissé ouvert (« Redis Pub/Sub au démarrage, migration possible vers un vrai broker »). Il
est arrêté : **Redis Streams**, et voici le raisonnement, parce qu'il sera reposé.

- **Pub/Sub ne persiste rien.** Un abonné arrêté au moment de la publication ne voit jamais l'événement.
  Sans conséquence pour une invalidation de cache ; inacceptable pour `user.registered`, dont dépend la
  création du compte Wallet — un événement manqué laisse un utilisateur sans wallet et rien pour le
  signaler.
- **Les Streams corrigent exactement ça, sur le Redis déjà déployé.** Les entrées persistent, chaque
  module a son *consumer group*, et une entrée reste en attente tant que le module ne l'a pas acquittée :
  un consommateur qui plante en cours de traitement la revoit au redémarrage.
- **Kafka règle le même problème** et apporte en plus le partitionnement, une rétention longue et le
  replay à profondeur arbitraire. Il apporte aussi un cluster à exploiter, superviser et maintenir en
  vie. Pour douze modules dont la plupart ne sont pas encore écrits, c'est un coût opérationnel réel face
  à un problème que les Streams résolvent déjà. **Déclencheur pour migrer vers Kafka** : le volume
  d'événements, un besoin d'ordonnancement inter-partitions, ou le replay de plusieurs mois d'historique.
  Le jour venu, seul `shared_kernel/events/bus.py` change — le reste du service ignore quel transport est
  dessous.

Un flux unique (`identity.events`) plutôt qu'un flux par type : l'ordre est ainsi garanti entre les
événements d'un même utilisateur, et un `role_changed` ne peut pas être livré après la suspension qui l'a
suivi. Les consommateurs filtrent par nom.

**Deux propriétés que les équipes consommatrices doivent connaître :**

1. **La livraison est *at-least-once*, jamais *exactly-once*.** Un consommateur qui plante entre le
   traitement et l'acquittement reverra l'événement. Les handlers doivent être idempotents. Aucun broker,
   Kafka compris, ne change cela sans coopération du handler.
2. **La rétention est bornée**, et un écrit peut réussir alors que la publication échoue — aucun
   transport ne ferme cet écart tout seul. C'est la raison d'être de `GET /users/backfill` : un module
   nouveau, ou absent au-delà de la fenêtre de rétention, y récupère les comptes créés depuis un instant
   donné. Sa consommation doit être idempotente elle aussi.

---

## 7. Migration des `auth` internes existants (DiddiGo)

DiddiGo a déjà une table `auth.users` réelle avec des comptes de test. Étapes de migration, à ne pas
sous-estimer :

1. DiddiFreeID exporte son schéma cible (celui ci-dessus).
2. Script de migration ponctuel : `auth.users` (DiddiGo) → `identity.users` (DiddiFreeID), en conservant
   les `id` existants pour ne pas casser les références déjà stockées côté `ride.rides.passenger_id` /
   `driver_profiles`.
   **Implémentation :** livré — `scripts/migrate_from_diddigo.py`. Idempotent, avec un mode `--dry-run` à passer
   systématiquement en premier. Le rôle `passenger` de DiddiGo devient `user` ; tout rôle ou statut non
   reconnu arrête la migration du compte concerné au lieu d'être deviné, et un téléphone déjà pris par un
   autre `id` est signalé pour arbitrage plutôt qu'écrasé.
3. DiddiGo bascule son `auth/infra` pour appeler DiddiFreeID (implémentation `HttpIdentityAdapter` du
   port `AuthProvider` déjà défini dans son `shared_kernel/contracts` — c'est exactement le point
   d'extension qu'ils avaient anticipé dans leur doc, section 6).
4. Le module `auth` interne de DiddiGo est supprimé une fois la bascule validée en test.
5. ~~Point d'attention explicite du STATUS_UPDATE DiddiGo : la validation KYC chauffeur (actuellement
   auto-approuvée) doit être resituée — probablement dans DiddiFreeID~~ — **Traité en v1.0.** Le portillon
   est implémenté ici (section 4 bis). Concrètement pour DiddiGo : leur processus de qualification
   chauffeur appelle `PATCH /users/{id}/role`, qui ouvre un dossier au lieu d'accorder le rôle, et ils
   attendent `user.role_changed` pour activer leurs fonctionnalités chauffeur. L'auto-approbation
   disparaît de leur côté.

---

## 8. Sécurité

- Hash des mots de passe (si utilisés) : Argon2id, pas bcrypt.
- Hash des codes OTP en base — jamais en clair (déjà le cas côté DiddiGo, à reprendre).
  **Implémentation :** en HMAC-SHA256 avec un poivre serveur, pas un SHA-256 nu. Un code à six chiffres n'a qu'un
  million de valeurs : un hachage non clé se renverse instantanément à partir d'un dump. Le poivre vit
  dans la configuration, pas dans la base — le dump seul est alors inutilisable.
- Rate limiting sur `/auth/otp/request` (429 déjà prévu côté contrat DiddiGo) — implémenté via Redis
  (compteur par téléphone + par IP).
  **Implémentation :** le compteur par IP n'est pas redondant avec celui par téléphone. Des numéros différents
  contournent le second ; c'est le premier qui arrête un script balayant une plage de numéros depuis une
  même machine. En cas d'indisponibilité de Redis, les deux basculent en *fail-open* : une panne de cache
  ne doit pas rendre l'inscription impossible, et le compteur `attempts` en base continue de borner
  l'abus.
- Limite de tentatives sur `/auth/otp/verify` (`attempts` en base) pour bloquer le brute-force du code à
  6 chiffres.
  **Implémentation :** le code est **consommé** une fois le plafond atteint, pas seulement rejeté. Sans cela, le
  plafond ne ferait que ralentir l'attaquant. L'incrément se fait en SQL, pour que deux tentatives
  concurrentes comptent bien pour deux.
- Tokens de refresh révocables individuellement (déconnexion d'un appareil précis) et globalement
  (déconnexion de tous les appareils — utile en cas de compte compromis).
  **Implémentation :** rotation à chaque usage, et **détection de réutilisation**. Présenter un refresh token déjà
  tourné révoque toutes les sessions de l'utilisateur : fuite et retry client sont indistinguables à cet
  endroit, et réémettre donnerait une durée de vie illimitée à un token volé.
- Journal d'audit (`user_status_history`) pour toute action admin, conforme à l'exigence transverse de
  traçabilité du cahier des charges.
  **Implémentation :** complété par `user_role_history` pour les décisions de rôle, refus compris.
- **Implémentation :** la suspension d'un compte révoque immédiatement tous ses refresh tokens. Sans cela, elle
  n'aurait d'effet qu'à l'expiration du JWT en cours.
- **Implémentation :** `/auth/otp/request` répond à l'identique pour un numéro connu et inconnu, cooldown armé dans
  les deux cas. Toute différence — un 404, un délai, un autre code — transformerait la route en oracle
  « cette personne est-elle chez DiddiFree ».
- **Implémentation :** les routes d'administration revérifient le compte en base au lieu de faire confiance au claim
  `role` du token. La lecture supplémentaire est négligeable sur un trafic back-office, et elle ferme la
  fenêtre pendant laquelle un administrateur révoqué détient encore un token qui dit le contraire.

---

## 9. État d'avancement

Les cinq étapes suggérées en v1 sont réalisées :

1. ✅ Squelette `identity_app/` et paire de clés RSA — `scripts/generate_keys.py` pour le développement ;
   en production les clés viennent du coffre-fort et sont montées en lecture seule, jamais dans le dépôt
   ni dans une image.
2. ✅ Commandes `RegisterUser` → `RequestOtp` → `VerifyOtp`, et au-delà : refresh avec rotation, logout,
   profil, rôles, KYC, administration.
3. ✅ `/.well-known/jwks.json` exposé, et vérification par un tiers sans appel à DiddiFreeID — testée en
   comptant les requêtes HTTP d'un consommateur simulé.
4. ✅ Script de migration DiddiGo — à lancer tôt, pendant que leur base de test est encore petite.
5. ✅ Port `IdentityVerifierPort` défini côté `shared_kernel`, avec son implémentation
   `JwksIdentityVerifier` prête à être copiée chez Wallet/Fund/Ride.

---

## 10. Questions ouvertes — à traiter en v2

Rien de ce qui suit ne bloque la v1.0 : le service est complet et cohérent tel qu'il est livré. Ce sont
des décisions délibérément reportées, chacune avec son déclencheur.

| Sujet | État en v1.0 | Ce que la v2 doit trancher |
|---|---|---|
| **Envoi SMS** | Port défini, implémentation de développement qui journalise le code | Contracter un agrégateur et écrire l'adaptateur. Rien d'autre ne bouge — c'est une classe de plus dans `infra`. Bloquant pour une ouverture publique |
| **Authentification par mot de passe** | Argon2id en place, colonne `password_hash` existante, aucune route ne l'expose | Ouvrir les routes le jour où un besoin back-office (DiddiLegal, DiddiSanté) se confirme |
| **KYC documentaire** | Le portillon est là (demande, file, décision, audit) ; la collecte de pièces ne l'est pas | Sous-module dédié : stockage des pièces, durées de conservation, qui y accède. Ne pas l'ajouter comme colonnes sur `users` |
| **Rôles multiples** | Un rôle principal unique par utilisateur | Une table de liaison, le jour où un `driver` doit aussi être `merchant`. Impacte le portillon KYC, qui raisonne aujourd'hui sur une demande à la fois |
| **Auth service-à-service** | Les deux formes implémentées et désactivables par configuration | Arbitrage réseau avec l'Infra (VPC interne, mTLS, clé d'API), puis retrait de celle qui n'est pas retenue |
| **Broker d'événements** | Redis Streams, persistant, at-least-once | Migrer vers Kafka si le volume, l'ordonnancement inter-partitions ou le replay long l'exigent. Un seul fichier change |
| **CQRS complet** | CQRS léger, une seule base | Introduire un read replica quand la latence de lecture devient un problème **mesuré** malgré cache et index |
| **Historique exposé en HTTP** | `user_status_history` et `user_role_history` écrites, interrogeables en base uniquement | Publier des routes de consultation quand une console d'administration en aura besoin |
