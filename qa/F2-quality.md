# F2 — 程式品質審查 (final verification, plan `nsysu-course-wrapper.md` §F2)

Executed 2026-08-28 on `main` (baseline `d1518b4`); fix commits `2d94c2e`, `c29d02f`, `26f06d9`, `d498ce2`.

## Verdict

**APPROVE** — every gate is green or carries an inline signed-off item with a written reason. No baseline-strictness parachute needed: all 30 mypy errors and all 48 ruff findings were tractable and are now fixed head-on (ruff 48→0, mypy 30→0).

## Tools + versions

| Tool | Version | How invoked |
|---|---|---|
| ruff (lint) | 0.16.5 | `cd backend && uv run ruff check .` (task's `uv run ruff check backend/` ≡ same file set, run from `backend/` because that's where the uv project lives) |
| mypy | 2.3.1 (compiled) | `cd backend && uv run mypy` (config `files = ["app"]`; `uv run mypy app` at baseline gave the same 30 errors) |
| pytest | 9.1.1 on Python 3.12.12 | `cd backend && uv run pytest` |
| tsc | 5.9.3 | `cd frontend && npx tsc --noEmit` |
| vitest | 4.1.11 (node v26.7.0) | `cd frontend && npx vitest run` |

ruff + mypy were absent from the project; they were added **pinned, into the `backend` dev dependency-group only** (plan hard constraint: installs live in the project venv). Lockfile updated by `uv add`; no existing dependency was upgraded.

## 1. Ruff — 48 → 0 (every finding triaged)

Baseline counts by rule → disposition:

| Rule | Count | Disposition | Reason |
|---|---|---|---|
| I001 unsorted-imports | 13 | **fixed** (`ruff --fix`) | mechanical import sorting |
| ISC004 implicit-string-concat-in-collection | 9 | **fixed** (hand) | each site read individually: ALL 9 were intentional multi-line concatenations (log/evidence message lines, JSON fixture fragments, URL+query join, HTML fixture wrapper) — **no missing commas anywhere**; all now explicitly parenthesized so the intent is structural, not accidental |
| B008 function-call-in-default (FastAPI `Depends` ×4) | 4 | **configured away** | FastAPI's documented DI idiom is exactly `= Depends(...)` in argument defaults; ruff's own recommended escape is `lint.flake8-bugbear.extend-immutable-calls`, now set in `backend/pyproject.toml`. These are DI seams, not shared-mutable-default bugs. Config carries the reason in a comment |
| UP017 datetime.timezone.utc → datetime.UTC | 4 | **fixed** (`ruff --fix`) | py312 modernization, no behavior change |
| F401 unused-import | 4 | **3 fixed + 1 noqa-signed** | tests: `Callable`, `parse_slt_result`, `HTTPException` removed (verified `parse_slt_result` was not a monkeypatch target). `alembic/env.py`: kept — it's a **side-effect import** that registers every table on `Base.metadata` for autogenerate; would have been silently deleted by `--fix`. Now `noqa: F401` with reason |
| UP012 unnecessary `"utf-8"` encode arg | 3 | **fixed** (`ruff --fix`) | `str.encode()` defaults to utf-8 |
| RUF059 unused unpacked variables | 3 | **fixed** (hand rename to `_`-prefixed) | test probes only needed the engine half of the tuple |
| DTZ001 naive datetime | 2 | **signed off, per-line reason'd noqa** | (a) `app/export/ics.py` VTIMEZONE `DTSTART` — **naive local time is mandatory** per RFC 5545 §3.6.5; attaching tzinfo would serialize an invalid property. (b) `tests/test_capture_windows.py` — the test deliberately feeds a naive datetime to assert the TypeError rejection hook. Both suppressed inline with the reason written on the spot |
| F541 f-string-without-placeholders | 1 | **fixed** (`ruff --fix`) | stray `f` prefix dropped |
| B009 getattr-with-constant | 1 | **fixed** (`ruff --fix`) | direct attribute access |
| PLR0402 manual-from-import | 1 | **fixed** (`ruff --fix`) | `from app.api import write_probe` |
| SIM102 collapsible-if | 1 | **fixed** (hand) | single condition chain, `tag == "input"` guard preserved (re-verified after edit) |
| SIM103 needless-bool | 1 | **fixed** (hand) | `return not nx` |
| RUF022 unsorted `__all__` | 1 | **fixed** (`ruff --fix`) | sorted |

**Not configured away / left alone on purpose:** `ruff format --check` reports 89 files would be reformatted — the project has never configured ruff-format, the F2 method names `ruff` (lint) not `format`, and reformatting the whole tree would be pure style churn; recorded here as a signed-off non-applicability of formatting rather than a finding.

Final tail (post-fix, post-commit):

```
$ uv run ruff check .
All checks passed!
```

## 2. Mypy — 30 errors / 11 files → 0 (82 source files)

No strict-baseline crusade was needed; every error was tractable and fixed at its type-contract seam:

| Category | Count | Disposition |
|---|---|---|
| Redis structural protocols declared `async def` (Coroutine returns) vs redis-py stubs (Awaitable returns) — `worker.py` ×2 | 2 | **fixed**: `AuthRedis` / `RedisLockClient` members re-declared as plain `def`s returning `Awaitable` (async-def fakes still satisfy; Coroutine <: Awaitable); the single real-client construction site gets one documented `cast` into a `_WorkerRedis` union protocol because redis-py stubs don't specialize on `decode_responses=True` |
| `PreviewResponse(**base)` dict-spread arg-type | 8 | **fixed**: explicit keyword arguments at both call sites (no runtime change) |
| `OpVerdict.course: CourseInfo \| None` dereferenced | 7 | **fixed**: honest narrowing in `_verdict_out` and the quota-date comprehension (`course is not None and ...`) |
| `_BreakerState`/`_Mode` used as annotations while typed `Final` | 3 | **fixed**: PEP 695 `type` statements |
| `Settings()` missing required `app_secret` (main/worker) | 2 | **signed-off scoped ignore**: pydantic-settings fills it from env at construction; mypy cannot see env. `# type: ignore[call-arg]` with reason comment — the alternative (a default `""`) would silently weaken the required-secret invariant |
| Untyped third-party imports (ddddocr, croniter, asyncpg) | 3 | **configured away**: per-module `ignore_missing_imports` overrides in `pyproject.toml` — these packages ship no `py.typed` and have no typeshed stubs; override is per-module so it cannot hide our own typed use of them |
| `QueueRedis` narrower reality (only `rpush` used; boundary injects `AuthRedis`) | 1 | **fixed**: protocol narrowed to exactly the producer method with the reason in its docstring |
| `_request_with_backoff(params)` signature too narrow for `None` | 2 | **fixed**: parameter typed `... \| None` |
| BeautifulSoup `Tag \| None` / multi-valued attribute iteration | 2 | **fixed**: `find_parent` re-narrowed behind `if link is not None`; `value is None` branch added to the typeshed union split |
| **totals** | **30** | 25 fixed in code + 2 scoped ignores + 3 per-module overrides → net effect: **0 errors** |

Final tail:

```
$ uv run mypy
Success: no issues found in 82 source files
```

## 3. Frontend

- `npm run lint` — **signed off as N/A with reason**: the project carries no ESLint dependency, no lint script, and no eslint config; `frontend/package.json` `build` is itself `tsc --noEmit && vite build`. Installing a whole ESLint stack here would be scope creep beyond the plan (F2 method's own parenthetical anticipates its absence). The frontend static gate is the two that exist and are green: `tsc --noEmit` and `vitest`.
- `npx tsc --noEmit` — **green** (baseline and post-fix; no frontend changes were needed).
- `npx vitest run` — **9 files / 107 tests, 107 passed**.

## 4. Security greps — all clean

| # | Command | Expected | Result |
|---|---|---|---|
| 1 | `grep -riE 'password' backend/app/models` | none | **0 hits** ✓ |
| 2 | `grep -riE 'cookie' backend/app/models` | none | **0 hits** ✓ |
| 3 | `grep -rn 'CSRF token' backend/app --include='*.py' \| grep -i log` | none | **0 hits** ✓ |
| 4 | CORS `*` in app code / Caddyfile | none | **clean**: `backend/app` contains no `CORSMiddleware` at all (documented same-origin posture — SPA+API share the Caddy origin, `ALLOWED_ORIGINS` is inert contract space whose default is an explicit localhost list; `docs/architecture.md` + `qa/17-grep.log` record this as intentional); Caddyfile `*` hits are path matchers only (`root *`, `handle /api/*`), never origins ✓ |
| 5 | `grep -rniE 'api[_-]?key\|secret\|token' backend/app --include='*.py' \| grep -v 'APP_SECRET\|csrf\|confirm\|session\|token_ttl\|TOKEN_TTL\|X-CSRF'` | each hit eyeballed, no hardcoded secrets | **clean**: every hit is a docstring/comment contract line, `pydantic.SecretStr` field, `secrets.token_urlsafe` (stdlib CSPRNG), salted-hash correlator, runtime-minted token (uuid4 lock tokens, school paging `?a=` anchors), or the env-driven `app_secret` field. Only credential literal in tree: `_DEV_DATABASE_URL`/`_DEV_REDIS_URL` dev-compose defaults (`postgres:postgres` to compose service names) — documented dev-only policy, `.env.example` contract, prod requires env override ✓ |
| 6 | `import httpx` under `backend/app` outside `app/selcrs/` | none | **clean**: strict import grep anchored to line start (`^\s*(import\|from)\s+httpx`) = 0 hits outside `app/selcrs/` (the only textual match outside it is the guardrail-explaining *comment* in `app/solver/loop.py`); selcrs-side users are `jar/__init__/sso2/http/endpoints.py` by design. The structural guardrail test `tests/test_selcrs_guardrail.py` additionally passes in the suite below ✓ |

## 5. Guardrail sweep — suites

Backend (host, no compose Postgres up — exactly the documented skip posture):

```
$ cd backend && uv run pytest
327 passed, 99 skipped, 67 warnings in 2.11s
```

Skip audit (`-rs` summary): all 99 skips counted and reason-checked — **94 × "compose Postgres unreachable"** (DB-backed tests: query/plans/auth-db/write engine/jobs/submit/resolve/audit-lifecycle/ICS-db/pool) and **5 × destructive opt-in skip in `tests/test_catalog_db.py`** ("destructive full-table wipes are opt-in: set CATALOG_DB_DESTRUCTIVE=1 AND provide a reachable Postgres"). **Zero unexpected skips, zero failures** — nothing to root-cause. The 67 warnings are a well-known starlette `TestClient` cookie-persistence DeprecationWarning cluster in existing tests; pre-existing, not introduced by F2, not a gate item.

**Todo-17 destructive gating: VERIFIED PRESENT** — `tests/test_catalog_db.py` module docstring declares the opt-in contract, and the 5 table-wiping tests skip unless `CATALOG_DB_DESTRUCTIVE=1` *and* a Postgres is reachable (runbook directs flagged runs at a scratch DB). This is a runtime-enforced gate, not just documentation.

Frontend:

```
$ cd frontend && npx vitest run
 Test Files  9 passed (9)
      Tests  107 passed (107)
```

## 6. Known hazards — status

- **Scripts not shipped in prod images** — documented limitation (deploy images build from `app/` + migrations only); left as-is per plan/task. No action.
- **Destructive `test_catalog_db` gating** — verified present and enforced (above).

## Commits (main)

| Hash | Message |
|---|---|
| `2d94c2e` | chore(tooling): pin ruff 0.16.5 + mypy 2.3.1 in dev group with F2 gate configs |
| `c29d02f` | fix(types): mypy 30->0 - Awaitable-returning redis protocols, Optional narrowing, PEP 695 aliases |
| `26f06d9` | style(lint): ISC004 parens, collapsed capture HTML branch, documented noqa sites (app/scripts/alembic) |
| `d498ce2` | style(lint): ruff clean across tests - import sorts, ISC004 parens, underscore-prefixed unused unpacks |

All gates above were re-run **after** the fix commits; tails shown are the post-commit green tails.
