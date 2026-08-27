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

## Write-path idempotency

`write_jobs.payload_hash` carries a **partial unique index** `WHERE status IN ('queued', 'running')`: at most one active job may exist per canonical payload hash, making double-click / confirm-token-replay a DB-enforced 409 (details land in todos 14–15).
