"""stu_enroll family adapter (tier-2; M1).

The tier-2 features live in FOUR school subsystems behind credential-forward
relay chains: regweb (registration checklist, reached by a 3-hop auto-submit
relay from stu_enroll_loginchk.asp), sco (interactive grades login with its own
captcha), tfstu (tuition page, relay-authed with zero interactive login), and
enrollcert (在學證明 PDF behind a checklist BUTTON relay). Everything here is
fixture-driven from the 2026-09-04 M0 rounds - see docs/stu-enroll-plan.md and
docs/verified-facts.md ("consolidated reading") for the live evidence.

Two hard-won invariants the modules below encode, both proven live:

1. ``build_client(cookies=jar)`` COPIES the passed jar - every Set-Cookie lands
   on ``client.cookies`` and must be re-read after EVERY call, or all requests
   go out anonymous (the M0 run-1 bug). All endpoint helpers therefore return
   the evolved jar alongside the page.
2. The school's handoff pages ECHO the plaintext password in hidden form
   fields. Pages passing through this package are memory-only by contract; the
   API layer must never cache or fixture them without masking.
"""
