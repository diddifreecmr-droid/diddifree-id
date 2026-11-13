# DiddiFreeID Observability v1

Ce document décrit l'implémentation locale de Diddi Observability v1 dans le
service DiddiFreeID. Le nom canonique de service est toujours `diddifree-id`.
Le nom du dépôt ou de l'application visible (`DiddiFreeID` / `diddiauth`) ne
doit pas être utilisé comme valeur de `service.name`.

## Signaux exposés

- **Logs** : JSON UTC sur stdout. Chaque entrée contient `service`,
  `service_version`, `environment`, `instance_id`, `component`, `event` et
  `request_id`; `trace_id` et `span_id` sont ajoutés lorsqu'une trace est
  active. Les en-têtes et corps HTTP ne sont jamais journalisés. Les valeurs
  ressemblant à un secret (`Authorization`, token, password, secret, API key,
  cookie) sont masquées dans la sortie JSON.
- **Métriques** : `GET /metrics`, format Prometheus, protégé par
  `Authorization: Bearer <METRICS_AUTH_TOKEN>`. Sans secret configuré, la
  route répond `503 METRICS_NOT_CONFIGURED`; les opérations métier restent
  disponibles. Les labels sont bornés : routes FastAPI normalisées, méthode,
  code HTTP, service, provider, résultat et nom de worker uniquement.
- **Traces** : OpenTelemetry est désactivé par défaut. Quand `OTEL_ENABLED`
  est vrai et qu'un endpoint OTLP HTTP est configuré, FastAPI et HTTPX sont
  instrumentés. `traceparent`/`tracestate` sont ajoutés comme métadonnées des
  entrées Redis Stream pour les événements de domaine, sans modifier leur
  payload contractuel.
- **Santé** : `/health/live` ne consulte aucune dépendance. `/health/ready`
  vérifie PostgreSQL, migrations, Redis, clés JWT et configuration OTP.
  `/health/workers` contrôle le heartbeat Redis de `account-purger`; son état
  ne rend pas l'API non-ready.

L'option historique `OTP_LOG_PLAINTEXT=true` reste une exception explicite
pour le staging et le diagnostic. Elle doit rester à `false` en production :
un code OTP est une donnée d'authentification et ne doit pas être centralisé
en clair.

## Raccordement DiddiObserve

L'équipe centrale doit fournir, via le coffre/Portainer et jamais via Git :

| Valeur | Utilisation |
| --- | --- |
| `METRICS_AUTH_TOKEN` | Bearer secret du scraper DiddiObserve et de Prometheus local |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | URL OTLP HTTP de traces complète, généralement terminée par `/v1/traces` |
| `OTEL_EXPORTER_OTLP_HEADERS` | En-têtes OTLP requis, format `cle=valeur,cle2=valeur2` |
| `SERVICE_INSTANCE_ID` | Identifiant stable de l'instance si `HOSTNAME` ne suffit pas |
| `SERVICE_VERSION` | Révision/version réellement déployée |

Configurer ensuite :

```ini
METRICS_AUTH_TOKEN=<secret-du-coffre>
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=<fourni-par-diddiobserve>
OTEL_EXPORTER_OTLP_HEADERS=<fourni-par-diddiobserve-si-requis>
SERVICE_VERSION=<revision-deployee>
SERVICE_INSTANCE_ID=<instance-ou-pod>
```

Le collecteur doit scraper le port interne `8000`, chemin `/metrics`, avec le
Bearer token ci-dessus. Il doit accepter les ressources OTLP suivantes :

```text
service.name=diddifree-id
service.version=<SERVICE_VERSION>
deployment.environment.name=<ENVIRONMENT>
service.instance.id=<SERVICE_INSTANCE_ID ou HOSTNAME>
diddifree.component=api
```

L'exporteur est asynchrone (batch processor). Une indisponibilité du
collecteur fait perdre ou retarder des signaux, mais ne bloque ni les requêtes
HTTP ni les commandes métier.

## Compose de revue

Les deux Compose ont été préparés, sans redéploiement :

- leur healthcheck applicatif utilise maintenant `/health/live` ;
- Prometheus écrit le secret de métriques dans un fichier temporaire privé et
  l'utilise par `authorization.credentials_file` ;
- `account-purger` reçoit Redis et possède son propre healthcheck basé sur le
  heartbeat.

En Portainer, renseigner les valeurs ci-dessus, reconstruire l'image puis
vérifier que Prometheus retrouve l'état `UP` pour `diddifree-id`. Ne pas
mettre les valeurs réelles dans une variable Git, un ticket ou une capture.

## Critères C01-C12

| Critère | Statut local | Mise en œuvre |
| --- | --- | --- |
| C01 identité | couvert | ressource canonique `diddifree-id`, version, environnement, instance, composant |
| C02 logs JSON UTC | couvert | formateur stdout JSON et timestamp RFC3339 UTC |
| C03 corrélation | couvert | `X-Request-ID` entrant/sortant, trace IDs quand OTEL est actif |
| C04 données sensibles | couvert avec exception documentée | absence de body/header et masquage défensif; `OTP_LOG_PLAINTEXT` est une exception contrôlée |
| C05 métriques communes | couvert | HTTP, dépendances, OTP, events, capabilities, tokens, service et workers |
| C06 cardinalité | couvert | route template et listes de labels bornées; aucun user ID, téléphone, e-mail, token ou request ID |
| C07 endpoint protégé | couvert | Bearer obligatoire, indisponible sans secret |
| C08 traces HTTP | couvert localement | OpenTelemetry FastAPI/HTTPX configurable vers OTLP |
| C09 traces asynchrones | couvert côté publication | W3C `traceparent`/`tracestate` ajoutés à Redis Stream; aucun consommateur asynchrone n'existe dans ce service |
| C10 santé | couvert | liveness indépendante et readiness des dépendances critiques |
| C11 workers | couvert | heartbeat, endpoint dédié, métriques et healthcheck `account-purger` |
| C12 résilience | couvert localement | échecs OTLP et du bus ne font pas échouer le métier; export batch non bloquant |

## Validation centrale encore requise

Les éléments suivants ne peuvent être déclarés conformes qu'après intervention
de DiddiObserve :

1. fournir l'endpoint OTLP et, si nécessaire, les en-têtes d'authentification ;
2. déposer `METRICS_AUTH_TOKEN` dans le coffre Portainer ;
3. redéployer après revue ;
4. confirmer dans DiddiObserve l'ingestion d'un log, d'une métrique et d'une
   trace corrélés avec le même `service.name` ;
5. interrompre volontairement le collecteur pour confirmer que l'authentification
   et les routes métier continuent de répondre.

L'absence actuelle d'un consommateur Redis local est le seul cas non applicable
à une validation de parcours asynchrone complet. La publication porte déjà le
contexte; le module qui consommera l'événement doit l'extraire avec la même
propagation W3C.
