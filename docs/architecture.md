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
- **School circuit breaker.** `BREAKER_FAILURE_THRESHOLD` (5) consecutive UNKNOWN SSO2 verdicts or transport failures open the breaker: `/api/auth/login` answers 503 locally with zero school contact and no streak feedback (read-only site unaffected). After `BREAKER_RECOVERY_AFTER` (300s) one half-open probe per minute is admitted; any coherent school answer (SUCCESS *or* CREDENTIAL-FAIL) closes it, another UNKNOWN re-stamps the wait.
- **Session-supersede rule.** A new successful login flips that student's `queued`/`running` write jobs to `session_superseded` in the same transaction as the student upsert (site-side single-session policy; the school provably tolerates concurrent sessions — `docs/verified-facts.md` live-verified (d)). The login itself is never blocked.
- **Hygiene.** `/api/auth/*` request bodies are never logged anywhere (uvicorn access log carries path+status only); the password is a `SecretStr` unwrapped exactly once at the adapter call; cookie values appear in Redis only.

## Write-path idempotency

`write_jobs.payload_hash` carries a **partial unique index** `WHERE status IN ('queued', 'running')`: at most one active job may exist per canonical payload hash, making double-click / confirm-token-replay a DB-enforced 409 (details land in todos 14–15).
