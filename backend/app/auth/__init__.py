"""Site-side auth subsystem (plan todo 8).

Owns everything between the SSO2 adapter and the HTTP router: the sliding-log
account lockout, the fixed clock-hour IP limiter, the school circuit breaker,
site sessions and the Redis-only selcrs credential store.

Credential policy (docs/architecture.md): passwords never persist in any form;
selcrs cookies live ONLY in Redis under ``selcrs:{site_session_id}`` with a
sliding/hard TTL pair - never Postgres, never logs.
"""
