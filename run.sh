#!/usr/bin/env bash
# Starts PulseGuard from a clean slate every time: any previous run's
# containers AND data are removed first, then the stack is started and
# waited on until every service is healthy.
source "$(dirname "$0")/scripts/common.sh"
require_docker

say "Clearing any previous run"
"${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true

say "Starting PulseGuard (fresh database, fresh Kafka, fresh baselines)"
"${COMPOSE[@]}" up -d --build --wait --wait-timeout 300 || {
  "${COMPOSE[@]}" ps
  die "Some services did not become healthy. Logs: docker compose -f pulseguard/docker-compose.yml logs <service>"
}
"${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'

url="http://localhost:$(dashboard_port)"
ok "PulseGuard is running: $url"
echo "    Stop everything with ./stop.sh"
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then open "$url" || true; fi
