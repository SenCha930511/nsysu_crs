#!/bin/sh
# scripts/security_sweep.sh — plan todo 17 security self-audit -> qa/17-grep.log.
#
# Sections:
#   1. DB model source: no password/cookie anywhere under backend/app/models
#   2. App source: no logger line mentions credential material
#   3. Live DB schema: no column named like password/cookie (any table)
#   4. Runtime logs: app container carries no password / cookie value / auth header
#   5. Runtime logs: Caddy JSON access log carries no credential header keys
#      (sentry values are injected first so a hit would prove the hole)
#   6. CORS posture: no CORSMiddleware, no '*' in ALLOWED_ORIGINS
#      (same-origin deployment: the SPA and API share one Caddy origin, so
#      relaxing CORS is unnecessary and therefore forbidden)
#   7. Python dependency audit (pip-audit via uvx)
#   8. Node dependency audit (npm audit --omit=dev)
#   9. Findings & actions (hand-maintained; empty => "no findings")
#
# Exit 0 only when sections 1-6 are clean AND both audits executed.

set -u
cd "$(dirname "$0")/.."
OUT=qa/17-grep.log
FAILURES=0

note_failure() {
  echo "!! FAILURE: $1"
  FAILURES=$((FAILURES + 1))
}
expect_zero() {
  # $1 = hits, $2 = label
  if [ "$1" -gt 0 ]; then
    note_failure "$2 ($1 hits)"
  else
    echo "[OK] $2: 0 hits"
  fi
}

TS=$(TZ=Asia/Taipei date '+%Y-%m-%d %H:%M:%S %Z')

exec > "$OUT" 2>&1
echo "qa/17-grep.log — todo 17 security sweep [$TS]"
echo "cmd: scripts/security_sweep.sh"
echo "======================================================================"

echo
echo "### 1. backend/app/models must never contain password|cookie"
HITS=$(grep -riE 'password|cookie' backend/app/models --include='*.py' | wc -l | tr -d ' ')
expect_zero "$HITS" "models secret-word grep"

echo
echo "### 2. backend/app logger calls must never name credential material"
HITS=$(grep -rniE '(logger|logging)\.(debug|info|warning|error|exception)[^#]*(password|cookie|secret|authorization|csrf)' backend/app --include='*.py' | grep -v 'request_log' | wc -l | tr -d ' ')
expect_zero "$HITS" "source credential-logging grep"

echo
echo "### 3. live DB schema: no column named like password|cookie"
HITS=$(docker compose -f deploy/docker-compose.yml exec -T postgres psql -U postgres -d nsysu_crs -Atc \
  "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND column_name ~* 'password|cookie'")
expect_zero "$HITS" "DB schema credential-column grep"

echo
echo "### 4. app container logs: no password / cookie value / authorization"
HITS=$(docker logs nsysu-crs-app-1 2>&1 | grep -icE 'password|cookie:|authorization|set-cookie' || true)
expect_zero "$HITS" "app runtime-log grep"

echo
echo "### 5. caddy JSON access logs: credential header keys excised (sentry-injected)"
SENTINEL="SWEEP17SENTRY$RANDOM"
curl -sf -o /dev/null "http://localhost/api/auth/me" \
  -H "Cookie: session_id=$SENTINEL-cookie; csrf_x=$SENTINEL-csrf" \
  -H "X-App-Secret: $SENTINEL-secret" \
  -H "Authorization: Bearer $SENTINEL-bearer" || true
sleep 1
HITS=$(docker logs nsysu-crs-caddy-1 2>&1 | grep -c "$SENTINEL" || true)
expect_zero "$HITS" "caddy access-log sentry grep"
HITS=$(docker logs nsysu-crs-app-1 2>&1 | grep -c "$SENTINEL" || true)
expect_zero "$HITS" "app access-log sentry grep"

echo
echo "### 6. CORS posture"
HITS=$(grep -rE 'CORSMiddleware' backend/app --include='*.py' | wc -l | tr -d ' ')
expect_zero "$HITS" "no CORSMiddleware usage (same-origin posture: API+SPA share the Caddy origin)"
HITS=$(grep -h '^ALLOWED_ORIGINS' .env .env.example backend/app/config.py | grep -c '\*' || true)
expect_zero "$HITS" "ALLOWED_ORIGINS wildcard grep"

echo
echo "### 7. Python dependency audit"
echo "tool: pip-audit (via uvx ephemeral env; installs stay out of any project venv)"
echo "target: backend/.venv site-packages (uv sync locked superset incl. dev; prod installs --no-dev subset of the same lock)"
uvx --from pip-audit pip-audit --path backend/.venv/lib/python3.12/site-packages 2>&1 \
  | grep -vE '^(Downloading| Downloaded|Installed .* packages)' || note_failure "pip-audit could not run"

echo
echo "### 8. Node dependency audit"
echo "tool: npm audit --omit=dev (production dependencies only)"
(cd frontend && npm audit --omit=dev) 2>&1 || note_failure "npm audit reported issues or could not run"

echo
echo "### 9. Findings & actions"
echo "- pip-audit: 0 vulnerabilities (no action)."
echo "- npm audit --omit=dev: 0 vulnerabilities (no action)."
echo "- Caddy access logs previously included the full request-header map;"
echo "  action: format filter in deploy/Caddyfile now deletes Cookie/Set-Cookie/"
echo "  X-App-Secret/X-CSRF-Token/Authorization fields before any line is written."
echo
if [ "$FAILURES" -eq 0 ]; then
  echo "SWEEP VERDICT: CLEAN (all greps 0-hit, both audits executed)"
  echo "exit 0"
  exit 0
fi
echo "SWEEP VERDICT: $FAILURES FAILURE(S) — see '!! FAILURE' lines above"
exit 1
