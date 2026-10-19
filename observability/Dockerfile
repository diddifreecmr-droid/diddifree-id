FROM prom/prometheus:v2.54.1 AS prometheus

COPY prometheus/prometheus.yml /etc/prometheus/prometheus.yml
COPY prometheus/alerts.yml /etc/prometheus/alerts.yml


FROM grafana/loki:3.3.2 AS loki

COPY loki/loki-config.yml /etc/loki/loki-config.yml


FROM grafana/alloy:v1.8.3 AS alloy

COPY alloy/config.alloy /etc/alloy/config.alloy


FROM grafana/grafana:11.2.0 AS grafana

COPY --chown=472:472 grafana/provisioning /etc/grafana/provisioning
# Keep provisioned dashboards outside Grafana's persistent data volume.
COPY --chown=472:472 grafana/dashboards /etc/grafana/dashboards
