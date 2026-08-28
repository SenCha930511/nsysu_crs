# Operations Runbook — NSYSU Course Wrapper

Single-host docker-compose deployment (VPS): `caddy` (only published entry, 80/443), `app`, `worker`, `postgres`, `redis`. All paths relative to the repo root unless noted.

---

## 1. Restart / daily ops

```bash
docker compose -f deploy/docker-compose.yml ps                       # health
docker compose -f deploy/docker-compose.yml restart app worker       # bounce pods
docker compose -f deploy/docker-compose.yml up --build -d            # rebuild+roll after a code change
docker compose -f deploy/docker-compose.yml logs -f app              # app logs (JSON access lines + uvicorn)
docker compose -f deploy/docker-compose.yml logs -f caddy            # edge JSON access log (headers filtered)
```

- Alembic after a schema change: `docker compose -f deploy/docker-compose.yml exec app alembic upgrade head`.
- **Redis eviction policy is pinned and must not change**: `noeviction` only. `volatile-*`/`allkeys-*` policies are FORBIDDEN — they would silently evict selcrs credential keys and the write queue.
- Non-root by design: app/worker run as uid 10001, caddy as 10002. Do not run `compose exec` debug shells as a different user expecting host file ownership to match.

**Host-debug port assumption.** Only 80/443 are published. To reach the app directly from the host (debugging only), create an untracked override:

```yaml
# deploy/docker-compose.debug.yml  (NEVER commit; delete after use)
services:
  app:
    ports: ["8000:8000"]
  postgres:
    ports: ["5432:5432"]
  redis:
    ports: ["6379:6379"]
```

`docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.debug.yml up -d` — remove the file when done. `docker-compose.dev.yml` already publishes 5432/6379/8000-via-caddy for dev and is the sanctioned dev path.

---

## 2. Backup & restore

**Backups** (daily, 14-file rotation): `scripts/backup.sh` dumps `nsysu_crs` via `pg_dump -F plain | gzip` into `deploy/backups/` and deletes everything past the newest 14 archives. Schedule on the host (cron; a systemd timer is equivalent):

```
17 3 * * * TZ=Asia/Taipei /absolute/path/to/repo/scripts/backup.sh >> /var/log/nsysu-crs-backup.log 2>&1
```

**Restore into the live DB** (destructive; stop writers first):

```bash
docker compose -f deploy/docker-compose.yml stop app worker
docker compose -f deploy/docker-compose.yml exec -T postgres psql -U postgres -qc "DROP DATABASE nsysu_crs" -qc "CREATE DATABASE nsysu_crs"
gunzip -c deploy/backups/nsysu_crs-<timestamp>.sql.gz | docker compose -f deploy/docker-compose.yml exec -T postgres psql -U postgres -d nsysu_crs -v ON_ERROR_STOP=1
docker compose -f deploy/docker-compose.yml start app worker
docker compose -f deploy/docker-compose.yml exec app alembic upgrade head   # no-op when dump is on head
```

**Verify a backup without touching live** (what `qa/17-backup.log` did): create `qa17_restore_scratch`, gunzip|psql into it, compare row counts (`courses, ingest_runs, students, plans, write_jobs, write_audit`), drop the scratch DB. Script: `scripts/qa17_backup_evidence.sh`.

---

## 3. Selection-window precheck (run before every 加退選/初選 window)

- [ ] `curl -sf http://localhost/api/health` → `{"status":"ok"}`; `docker compose ps` all `healthy`.
- [ ] `scripts/backup.sh` run manually once; newest archive < 26h old; rotation count ≤ 14.
- [ ] Catalog freshness: `curl -sf http://localhost/api/catalog/meta` → `ok:true`, `updated_at` within the last cron period; peak cadence active (`CATALOG_CRON_PEAK=*/10 * * * *`, `CATALOG_PEAK_DATES` covers the window).
- [ ] Peak-cycle fit: last off-peak full ingest time (worker log) comfortably < 10min; if not, drop to diff-dept ingest per plan todo 6 and announce in meta.
- [ ] Breaker clean: `curl -sf -H "X-App-Secret: $APP_SECRET" http://localhost/api/ops/state` → `state:"closed"`, `streak:0`, lockout totals at baseline.
- [ ] `FEATURE_FIRST_ROUND_WRITE=false` unless the milestone terms say otherwise (see `docs/launch-checklist.md`).
- [ ] Disk: `df -h /` headroom ≥ 2GB; `docker system df` for dangling space.

## 4. School appears blocked / unreachable (尖峰掛站)

Symptoms: login 503s, ingest rounds fail, breaker eventually opens.

1. Confirm on our side: `docker compose logs --tail=50 app worker | grep -i selcrs` — `SelcrsUnavailable`/timeouts against selcrs.
2. Confirm externally: hit the school's public course query page from the host network; check with school IT channels whether it is a known outage.
3. **Do nothing heroic**: the breaker opens after 5 consecutive failures and puts the site into degraded read-only automatically (banner on every page: catalog/timetable keep working; login/write locally 503). Recovery is automatic — after `BREAKER_RECOVERY_AFTER=300`s, half-open probes (1/60s) and the first coherent answer closes it.
4. Communicate status: verify the public posture at `/api/ops/state` (`open` / `half-open`). If the outage is prolonged, note it in the status channel per launch comms; the meta banner already carries the last successful snapshot time.
5. Post-incident: check `lockouts` totals for abuse overlap and recent ingest `ok=false` spans; recover freshness by letting one normal cron tick run, then verify `meta.ok:true`.

## 5. SSO2 failure degrade (學校登入路徑失效)

Symptoms: SSO2 verdicts flip to UNKNOWN en masse (login page redesign, marker drift), breaker opens even though the school is "up".

1. Verify with the probe scripts: `docker compose -f deploy/docker-compose.yml exec app python -m scripts.stage_probe` (read-only run) and a capture-kit run in a selection window where legal (`scripts/capture/`).
2. Mark posture truthfully: the breaker/banner degrade is the correct user-facing state — do NOT disable the breaker to "hide" it.
3. Fix forward: update `app/selcrs/sso2.py` markers from fresh captures (plan: 雙變體容差), add fixtures, redeploy (`up --build -d`). The breaker closes itself once coherent answers probe through.
4. If SSO2 is retired by the school structurally: that is the plan's `BLOCKED-ON-USER-DECISION` path — the site remains read-only indefinitely until a decision; do not build the captcha (Studcheck.asp) fallback without a plan change.

## 6. `鎖定濫用` (targeted lockout abuse) alert SOP

Signal: `lockouts.today`/total climb abnormally in `/api/ops/state` (baseline ≈ 0–few/day; a spike, or repeated daily locks, means someone is burning 5-fails-per-15min against victim student numbers — see FAQ Q4 / TOS §鎖定濫用 for the accepted-risk rationale).

1. Query posture: `curl -sf -H "X-App-Secret: $APP_SECRET" http://localhost/api/ops/state` — compare `today` vs `total` history.
2. Scope the sources: Caddy JSON access log on the VPS (`docker compose logs caddy`) for login-attempt cadence per `client_ip` — our limits: per-account 5/15min, per-IP 30/clock-hour.
3. If a narrow set of IPs dominates: optionally rate-limit at the edge (Caddy `retry_after` or firewall rule per-host firewall — host-level iptables/nftables REJECT for the source CIDR, noting dorm-NAT caveats).
4. If distributed (credential-stuffing pattern): announce degraded honesty in the FAQ/status channel — the per-account locks ARE working as designed; victims' school passwords are never at risk from us (we store nothing), and the school side has its own defenses.
5. Never respond by loosening `LOGIN_FAIL_LIMIT`/`LOGIN_LOCK_MINUTES` globally — per plan, the lock IS the defense; response is monitoring + edge filtering + communication.
6. Record the incident (window, counts, actions) in the ops log; if a victim reports, advise per the next section.

## 7. 預設密碼（身分證後六碼）勸導回應

When a user asks or a report indicates they still use the default password:

- School's default = 身分證字號後六碼 — anyone knowing 學號+身分證後六碼 can log in as them **at the school**, independent of this site.
- Our site cannot change it for them (no password storage, no托管) and never will: direct them to change it **on the school system**.
- Point at FAQ Q2 and TOS §預設密碼更換勸導（same wording）; if abuse seems active, treat as §6 incident.

## 8. Destructive DB tests (operator note)

`backend/tests/test_catalog_db.py` wipes the whole catalog tables. It runs **only** with `CATALOG_DB_DESTRUCTIVE=1` AND a reachable Postgres, and even then it must target a scratch DB, never live:

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres psql -U postgres -c "DROP DATABASE IF EXISTS qa17_scratch" -c "CREATE DATABASE qa17_scratch"
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml run --rm --no-deps -T \
  -e DATABASE_URL=postgresql://postgres:postgres@postgres:5432/qa17_scratch worker \
  sh -c "uv run alembic upgrade head && CATALOG_DB_DESTRUCTIVE=1 uv run pytest tests/test_catalog_db.py -q"
```

---

## 9. Environment knob table

| Knob | Default | Meaning / ops guidance |
|---|---|---|
| `DATABASE_URL` | compose DSN | Postgres async DSN. Wrong → 503s (never leaks in responses); see `qa/01-bad-db.log`. |
| `REDIS_URL` | compose DSN | Redis DSN. Down → login/write hard-fail, reads stay up (plan-pinned). |
| `APP_SECRET` | — | Site secret: confirm-token HMAC, `/api/ops/state` admin gate. Rotate = invalidate all confirm tokens/sessions. Never commit a real value. |
| `SEMESTER_YEAR_SEM` | `1151` | Catalog key `D0` = YYY+S (e.g. 1151 = 115-1). |
| `SEMESTER_START_DATE` / `SEMESTER_END_DATE` | 2026-09-01 / 2027-01-16 | ICS window + plan logic; end date becomes ICS `UNTIL` (UTC DATE-TIME). |
| `ALLOWED_ORIGINS` | localhost origins | Inert contract (no CORS middleware — same-origin posture; never `*`). |
| `TZ` | `Asia/Taipei` | All containers + app clock; lockout day buckets, log timestamps. |
| `CATALOG_CRON_OFFPEAK` / `CATALOG_CRON_PEAK` | `7 * * * *` / `*/10 * * * *` | Ingest cadence; peak only on `CATALOG_PEAK_DATES`. Singleton-locked in Redis. |
| `CATALOG_PEAK_DATES` | empty | Comma list of peak dates (`2026-08-28,...`); wrong date ⇒ off-peak cadence. |
| `FEATURE_FIRST_ROUND_WRITE` | `false` | 初選志願 write flag. **Must stay false until the 115-2 window live-verifies** (milestone terms; enabling = v1.1.0 event). |
| `SELCRS_SESSION_TTL_SLIDING` | `1800` | selcrs jar sliding TTL (s); refreshed on school activity. |
| `SELCRS_SESSION_TTL_HARD` | `7200` | selcrs jar hard cap (s) from issuance; then 401 `SELCRS_EXPIRED`. |
| `WRITE_QUEUE_DWELL_MAX` | `600` | Max queue dwell (s) before honest auto-cancel. |
| `CONFIRM_TOKEN_TTL` | `300` | Write-confirm token TTL (s); single-use (GETDEL). |
| `CSRF_TOKEN_TTL` | `900` | CSRF cookie TTL (s); slides on each write call. |
| `LOGIN_FAIL_LIMIT` | `5` | Per-account CREDENTIAL-FAIL budget inside the sliding 15-min log. |
| `LOGIN_LOCK_MINUTES` | `15` | Fixed lock length (min); also the failure-entry individual window. |
| `LOGIN_IP_HOURLY_LIMIT` | `30` | Per-IP login attempts per fixed clock-hour (every attempt counts). |
| `BREAKER_FAILURE_THRESHOLD` | `5` | Consecutive SelcrsUnavailable-class failures → breaker opens site-wide read-only. |
| `BREAKER_RECOVERY_AFTER` | `300` | Wait (s) before half-open probing starts; coherent probe closes. |
| `CATALOG_DB_DESTRUCTIVE` | unset | TEST-ONLY opt-in for full-table-wipe tests (see §8). Never set in any runtime env file. |
