#!/bin/sh
# Evidence generator for qa/17-smoke.log: hardened prod compose smoke.
set -eu
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f deploy/docker-compose.yml"
C() { docker compose -f deploy/docker-compose.yml exec -T "$@"; }

{
  echo "qa/17-smoke.log — todo 17 prod-hardened compose smoke [$(TZ=Asia/Taipei date '+%Y-%m-%d %H:%M:%S %Z')]"
  echo "cmd: scripts/qa17_smoke.sh (expects the rebuilt stack already up: docker compose -f deploy/docker-compose.yml up --build -d)"
  echo "======================================================================"
  echo
  echo "## compose ps (all healthy)"
  $COMPOSE ps --format '{{.Name}} {{.Status}}'
  echo
  echo "## 200 smoke through Caddy (the only published entry)"
  for route in / /api/health /api/catalog/meta /api/ops/state /privacy /tos /faq; do
    printf '%-22s -> HTTP_%s\n' "$route" "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost$route")"
  done
  echo
  echo "## bodies of the API smokes"
  echo '--- /api/health'; curl -sf http://localhost/api/health; echo
  echo '--- /api/catalog/meta'; curl -sf http://localhost/api/catalog/meta; echo
  echo '--- /api/ops/state (public posture)'; curl -sf http://localhost/api/ops/state; echo
  echo '--- /api/ops/state (admin, X-App-Secret)'; curl -sf http://localhost/api/ops/state -H "X-App-Secret: $(grep '^APP_SECRET=' .env | cut -d= -f2-)"; echo
  echo
  echo "## security headers dump (curl -sI http://localhost/)"
  curl -sI http://localhost/ | grep -iE '^HTTP|content-security-policy|x-content-type-options|x-frame-options|referrer-policy|^server:'
  echo
  echo "## non-root containers (app/worker/caddy uid; postgres/redis drop via official entrypoints)"
  for svc in app worker caddy; do printf '%-8s uid=%s\n' "$svc" "$(C "$svc" id -u)"; done
  for c in nsysu-crs-postgres-1 nsysu-crs-redis-1; do
    printf '%-24s pid1-uid=%s\n' "$c" "$(docker exec "$c" awk '/^Uid:/{print $2}' /proc/1/status)"
  done
  echo
  echo "## published ports (only caddy 80/443; everything else internal)"
  for c in nsysu-crs-app-1 nsysu-crs-worker-1 nsysu-crs-postgres-1 nsysu-crs-redis-1 nsysu-crs-caddy-1; do
    printf '%-24s %s\n' "$c" "$(docker inspect "$c" --format '{{json .HostConfig.PortBindings}}')"
  done
  echo
  echo "## container TZ spot check"
  echo "app=$(C app date +%Z) caddy=$(C caddy date +%Z)"
} > qa/17-smoke.log 2>&1

cat qa/17-smoke.log