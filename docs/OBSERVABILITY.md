# Observabilité DiddiFreeID

## V1 livrée

DiddiFreeID expose les signaux suivants :

- logs JSON sur stdout Docker ;
- `X-Request-ID` propagé dans les requêtes et la réponse ;
- `/health/live` pour la disponibilité du processus ;
- `/health/ready` pour PostgreSQL, les migrations, Redis, les clés JWT et le fournisseur OTP ;
- `/metrics` au format Prometheus ;
- métriques HTTP, OTP, événements Redis, service tokens, capabilities et santé des dépendances.
- logs JSON centralisés dans Loki via Grafana Alloy.

Les labels Prometheus n'utilisent pas d'identifiant utilisateur, de téléphone, d'e-mail ou de token.

## Stack locale et Portainer

Les deux fichiers Compose démarrent :

- Prometheus sur `${PROMETHEUS_HOST_PORT:-19090}` ;
- Grafana sur `${GRAFANA_HOST_PORT:-13000}` ;
- Loki sur `${LOKI_HOST_PORT:-13100}` ;
- PostgreSQL et Redis sur leurs ports déjà configurables.

Prometheus scrape `http://app:8000/metrics` sur le réseau Docker interne. Grafana est préconfiguré
avec Prometheus, Loki et le dashboard `DiddiFreeID Overview`. Alloy lit les logs Docker uniquement
pour les conteneurs portant le label `com.diddifree.observability=true`.

Les logs sont conservés dans le volume `loki_data` avec une rétention initiale de 7 jours. Le volume
`alloy_data` conserve la position de lecture afin d'éviter de renvoyer tout l'historique après un
redémarrage.

Dans Portainer, définir au minimum :

```ini
PROMETHEUS_HOST_PORT=19090
GRAFANA_HOST_PORT=13000
LOKI_HOST_PORT=13100
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<secret-fort>
```

Le mot de passe Grafana ne doit pas être ajouté à Git. Les volumes `prometheus_data`, `grafana_data`,
`loki_data` et `alloy_data` doivent être conservés lors des redeploys.

## Alertes V1

Les règles livrées couvrent :

- cible DiddiFreeID indisponible ;
- taux HTTP 5xx supérieur à 5 % ;
- latence p95 supérieure à une seconde ;
- dépendance unhealthy ;
- lecture de capability obsolète.

Prometheus évalue les règles, mais la notification nécessite encore un Alertmanager ou l'intégration
de notification choisie par l'infrastructure.

## V2 restante

- Alertmanager et routage vers Telegram/e-mail/Slack ;
- tracing OpenTelemetry avec `trace_id` entre les modules ;
- SLO/SLI, rétention et runbooks d'incident ;
- métriques d'infrastructure PostgreSQL, Redis et conteneurs.
