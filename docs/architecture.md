# Architecture notes

Living document for cross-todo structural decisions in `.omo/plans/nsysu-course-wrapper.md`.

## Credential storage policy

This project never persists school credentials:

- **School password** — never stored in any form (no plaintext, no hash, no "remember me"). It exists only in memory during a login or write-confirmation request.
- **selcrs session cookie** — treated as a credential. It lives **only in Redis** under the key `selcrs:{site_session_id}` with:
  - a sliding TTL of `SELCRS_SESSION_TTL_SLIDING` seconds (default 1800) refreshed on activity, and
  - a hard cap of `SELCRS_SESSION_TTL_HARD` seconds (default 7200) from issuance.
  - It is **never** written to Postgres and never written to logs. Redis failure means login/write hard-fail while read paths stay available.
- **Postgres** stores only: `students` (student number), `plans` / `plan_items` (candidate plans), `courses` / `ingest_runs` (scraped catalog), and the write path ledger `write_jobs` / `write_audit` / `write_audit_archive_meta`. `write_audit` correlates students via a **salted `stuid_hash`**, never the raw student number (PII lifecycle: hot 90 days → de-identified gz archive 1 year → delete).
- There is intentionally **no `selcrs_sessions` table**.

## Login throttling & circuit breaker (todo 8)

- **Per-account sliding-log lockout.** Only real `CREDENTIAL-FAIL` verdicts from the school are appended — one Redis sorted-set member per failure, scored with its own 15-minute expiry (`loginfail:{student_no}`); unexpired failures ≥ `LOGIN_FAIL_LIMIT` (5) set a fixed 15-minute lock (`loginlock:{student_no}`, written `NX EX` exactly once — it never extends). While locked, login is rejected locally with 429 before any school call and the rejection is *not* appended to the log. When the lock lapses the log has also decayed entry-by-entry to a clean window, so an attacker must re-accumulate. A successful login never clears the log (a victim's login must not refund an attacker's budget). Residual risk accepted per plan: ~20 failures/hour can keep one account near-permanently locked — mitigated by lockout-event monitoring/alerts (todo 17 runbook/FAQ).
- **Secondary IP limit: 30 requests per fixed clock-hour** (`loginip:{ip}:{floor(epoch/3600)}`, INCR per attempt). Every attempt counts, including locally-rejected 429s on a locked account. The window is the wall-clock hour (dorm-NAT rationale: campus housing puts many students behind one NAT address, so the binding quota is the per-account log above; the IP limit only stops distributed brute force at obviously-non-human rates).
- **School circuit breaker.** `BREAKER_FAILURE_THRESHOLD` (5) consecutive UNKNOWN SSO2 verdicts or transport failures open the breaker: `/api/auth/login` answers 503 locally with zero school contact and no streak feedback (read-only site unaffected). After `BREAKER_RECOVERY_AFTER` (300s) one half-open probe per minute is admitted; any coherent school answer (SUCCESS *or* CREDENTIAL-FAIL) closes it, another UNKNOWN re-stamps the wait. Extended to every school-touching endpoint in todo 17 — see “Breaker — site-wide degraded read-only posture” below.
- **Session-supersede rule.** A new successful login flips that student's `queued`/`running` write jobs to `session_superseded` in the same transaction as the student upsert (site-side single-session policy; the school provably tolerates concurrent sessions — `docs/verified-facts.md` live-verified (d)). The login itself is never blocked.
- **Hygiene.** `/api/auth/*` request bodies are never logged anywhere (uvicorn access log carries path+status only); the password is a `SecretStr` unwrapped exactly once at the adapter call; cookie values appear in Redis only.

## Write-path idempotency

`write_jobs.payload_hash` carries a **partial unique index** `WHERE status IN ('queued', 'running')`: at most one active job may exist per canonical payload hash, making double-click / confirm-token-replay a DB-enforced 409 (details land in todos 14–15).

## Breaker — site-wide degraded read-only posture (todo 17)

The todo-8 breaker (`app/auth/breaker.py`, unchanged semantics) became the single outage oracle for **every** school-touching API surface:

- `/api/auth/login` and `/api/write/submit` — admit + record wiring since todo 8/15 (unchanged).
- `/api/auth/write/preview`, `/api/stage`, `/api/me/selections/sync` — same wiring since todo 17: jar checks stay first (local), then `breaker.admit()`; while open they answer 503 **locally** with zero school contact. `SelcrsUnavailable` outcomes feed the streak; any coherent outcome (including a login-page bounce, which proves the host speaks its protocol) closes/resets it.
- `/api/write/jobs/{id}` is **not** gated: it is a pure Postgres read of our own ledger (no school contact), so the read-only posture keeps it available. Zero-queueing is enforced at preview+submit, the only enqueue paths.
- The **worker** (write engine) and the **catalog ingest loop** deliberately do not feed or consult the breaker: queued jobs carry their own bounded transport-retry semantics (todo 15), and the ingest loop reports its own degrade via `ingest_runs.ok=false` + the meta banner. The breaker is the API-layer posture.

Recovery (todo-8 semantics, coherence verified): `BREAKER_FAILURE_THRESHOLD=5` consecutive `SelcrsUnavailable`-class failures opens; `BREAKER_RECOVERY_AFTER=300`s after the *last* failure, one half-open probe per 60s gate is admitted. A coherent probe answer closes everything; a failed probe re-stamps the wait — so only probe-alive success closes the breaker (any failure restarts the wait).

## `/api/ops/state` — posture + abuse counters (todo 17)

One route, two trust levels:

- **Public** (any client): `breaker.state` (`closed`/`open`/`half-open`) and `mode` (`normal`/`read-only`) — exactly what the SPA's global banner polls. Never touches `admit()` (reporting must not consume the half-open probe gate).
- **Admin** (adds `streak`, `opened_at`, thresholds, `lockouts {today,yesterday,total}`): gated by `X-App-Secret: <APP_SECRET>` (constant-time compare) **or** a direct loopback peer (no proxy in between; through Caddy the peer is Caddy's container IP, so use the header). Runbook: `curl -H "X-App-Secret: $APP_SECRET" http://localhost/api/ops/state`.

Lockout abuse counters (todo 17): `FailureLog.record_credential_fail` increments `lockout:events:total` and `lockout:events:<YYYYMMDD-in-TZ>` (30d TTL) **only** when a *new* `loginlock:*` key is created (NX success) — aggregate counters, no student identifiers, feeding the `鎖定濫用` monitor/alarm SOP in `docs/runbook.md`.

## Request access log (todo 17)

`app/request_log.py` middleware (outermost): honors an incoming `X-Request-ID` (≤64 chars, else mints a uuid4), echoes it on the response, and emits one line on the `app.access` logger whose message is a single JSON object:

```json
{"ts":"2026-08-28T09:33:51.687+08:00","request_id":"...","method":"GET","path":"/api/ops/state","status":200,"latency_ms":62.6}
```

Fields: `ts` (app TZ, millisecond ISO), `request_id`, `method`, `path` (path only — **never** a query string), `status`, `latency_ms`. Never logged: request/response bodies, headers (so no `Cookie`/`Authorization`/`X-CSRF-Token`/`X-App-Secret`), client IP. Uvicorn's own access line (method + request line + status) also stays on and may carry a query string; credentials never travel in query strings by design (all auth material is POST-body JSON). Grep-tested in `tests/test_request_log.py` and by `scripts/security_sweep.sh` (sentry-injected Cookie/secret headers must not appear in either the app or the Caddy access log; Caddy's `format filter` excises those header fields).

## Database pool resilience (todo 17)

`build_engine` sets `pool_pre_ping=True`: every checkout probes liveness and transparently recycles dead backends, so a Postgres recreate/restart no longer fails one request per stale pooled connection (observed as a transient `/api/catalog/meta` 500 before the fix). Behavioral pin: `tests/test_db_pool.py` kills the pool's own backend out-of-band and asserts the next checkout still answers.

## HTTP edge hardening (todo 17)

- Only Caddy publishes ports (80, +443 reserved for the VPS domain); `app`/`worker`/`postgres`/`redis` listen on the internal network only. Host-debug port publishing lives in `docs/runbook.md` as an override snippet.
- `app`/`worker` run as uid 10001, Caddy as uid 10002 (compose sysctl `net.ipv4.ip_unprivileged_port_start=0` lets it bind 80/443); postgres/redis official images already drop to their own non-root daemon users.
- Caddy sends `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, a CSP tuned to the built SPA (`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` — no inline scripts exist in the Vite build; `'unsafe-inline'` covers React `style=` attributes), and a CS-Poisoning-free HSTS line that stays **commented** until the real domain serves HTTPS (see the comment in `deploy/Caddyfile`).
- **CORS posture: none, on purpose.** The SPA and API share one origin through Caddy, so no `CORSMiddleware` exists; `ALLOWED_ORIGINS` is inert contract space (kept for the dev-origin case) and must never contain `*`. Introducing CORS relaxation is a plan change.

## Backups (todo 17)

`scripts/backup.sh`: `pg_dump -F plain | gzip` of the compose Postgres into `deploy/backups/nsysu_crs-<timestamp>.sql.gz`, rotation keeps the newest 14. Schedule daily (03:17 Asia/Taipei) via host cron/systemd (exact line in `docs/runbook.md`). `deploy/backups/` is gitignored (dumps contain user data). Restore runbook: `docs/runbook.md`; restore proof: `qa/17-backup.log` (scratch-DB restore, row counts match live).
