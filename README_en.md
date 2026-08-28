# NSYSU Course Wrapper (English)

[繁體中文 (Traditional Chinese)](README.md) | **English**

---

A modern course selection wrapper and planning system designed for National Sun Yat-sen University (NSYSU). It provides an intuitive catalog browser with multi-dimensional filtering, an interactive weekly timetable with real-time clash and credit validation, direct syllabus links, PNG timetable export, and school selection synchronization. Under strict **human-in-the-loop confirmation** and high-standard security guardrails, it supports asynchronous proxy course add/drop submissions.

**Tech Stack**: FastAPI / Vite + React 18 + TypeScript + Bootstrap 5 / PostgreSQL 16 + Redis / Caddy

---

## Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Safety & Privacy](#safety--privacy)
4. [Quickstart (Production)](#quickstart-production)
5. [Local Development](#local-development)
6. [Testing & Verification](#testing--verification)
7. [Documentation](#documentation)
8. [Recent Highlights](#recent-highlights)
9. [Attribution & License](#attribution--license)

---

## Features

| Access Tier | Target Audience | Overview |
|---|---|---|
| **Public Browser** | Anyone (No login required) | Virtualized course catalog browsing for high-performance rendering, keyword search, **advanced multi-criteria filters** (department / grade / credits / compulsory or elective / EMI / available seats / weekday / period), direct links to official course syllabus pages (new tab), and instant bilingual switching (Traditional Chinese ⇄ English). |
| **Timetable Planner** | Guests / Anonymous | Local staging (localStorage), visual weekly timetable preview, real-time schedule conflict detection, automatic calculation of credits and hours, and high-resolution PNG timetable export. |
| **Student Zone** | Enrolled Students (SSO2 Authentication) | Real-time synchronization of current enrolled courses, staged add/drop submission (with priority support), submission preview and **two-factor password re-confirmation**, asynchronous background queue processing (Redis Queue + Background Worker), and live job tracking with verbatim school feedback (e.g. "Violation of course restriction", with student IDs automatically masked). |

---

## Architecture

```mermaid
flowchart LR
  U[Browser (Guest / SSO2 Login)] --> C[Caddy Reverse Proxy: / + /api + Security Headers/CSP]
  C --> A[FastAPI Backend Application]
  A --> P[(PostgreSQL 16 Database)]
  A --> R[(Redis: Cache / Session / Breaker / Queue)]
  A --> S[NSYSU selcrs / SSO2 Integration]
  W[Worker Service: Catalog Ingest + Queue Worker] --> P
  W --> R
  W --> S
```

- **Caddy (`deploy/`)**: The unified HTTP(S) entrypoint (ports 80/443) serving static frontend assets and reverse-proxying `/api/*`, configured with strict Content Security Policy (CSP) and security headers.
- **FastAPI Backend (`backend/app/`)**:
  - **Catalog & Search**: `/api/courses` (paginated queries), `/api/catalog/meta` (data freshness), `/api/catalog/depts` (department dropdown, Redis-cached for 30 minutes), and `/api/courses/{id}/outline` (syllabus proxy).
  - **Authentication & Security**: `/api/auth/*` (SSO2 flow, password handling, session cookies), brute-force lockout counters, and an automatic circuit breaker for school endpoints.
  - **Write Pipeline**: `POST /api/write/preview` (form echo) → `POST /api/write/submit` (password re-confirmation + CSRF token, enqueued to Redis) → `GET /api/write/jobs*` (job audit ledger).
  - **Privacy Conventions**: Forbidden/unauthorized internal endpoints return HTTP 404 (instead of 401/403) to prevent structure disclosure.
- **Worker Service (`python -m app.worker`)**: Background worker that periodically ingests course catalog updates and consumes the write queue (`writeq:jobs`), ensuring real school POST requests never block core API threads.
- **PostgreSQL 16**: Relational storage for student records, the course database (with exact course code mapping), catalog sync runs, and write audit logs (90-day hot retention with de-identified archival).
- **Redis**: Handles site sessions, short-lived school credentials, circuit breaker state, department cache, and write queue idempotency.
- **React 18 Frontend (`frontend/src/`)**:
  - Built with Bootstrap 5 and custom design system tokens (no Tailwind dependency).
  - High-performance virtualized course list via React Virtuoso.
  - Timetable PNG image export powered by `html2canvas` with canvas validation.
  - Modular scheduling and conflict detection engine (`lib/timeslots.ts`, `lib/selectionGrid.ts`).

---

## Safety & Privacy

1. **Zero-Credential Storage**: Passwords are never stored in the database or written to logs. School session credentials reside only in Redis with a short TTL.
2. **Human-in-the-Loop Confirmation**: All write actions require explicit form previewing and manual password re-confirmation before being queued for dispatch.
3. **PII Protection**: Audit records correlate student identity using salted hashes, and student numbers are masked across the interface (e.g. `M123****78`).
4. **Rate Limiting & Circuit Breaker**: Account-level failed login throttling and school endpoint outage detection protect against abusive requests and prevent unnecessary load on school systems.
5. **Strict Content Security Policy**: Configured with `script-src 'self'`, eliminating the execution of unauthorized inline scripts.

---

## Quickstart (Production)

```bash
# 1. Copy environment template and fill in required variables (e.g., APP_SECRET)
cp .env.example .env

# 2. Build and launch all containers
docker compose -f deploy/docker-compose.yml up --build -d

# 3. Verify health
curl -sf http://localhost/api/health        # Health check via Caddy
curl -sf http://localhost/                  # Frontend home
curl -sf http://localhost/api/ops/state     # System posture & breaker state
```

- **Backups**: Run `scripts/backup.sh` to produce a compressed `pg_dump | gzip` backup under `deploy/backups/` (retains the latest 14 snapshots).
- **Service Updates**: When updating backend routes or models, use `docker compose up --build -d` to ensure container dependencies and caches remain consistent.

---

## Local Development

```bash
# Option A: Docker Compose with hot reloading
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build

# Option B: Bare-machine execution
# Backend (FastAPI)
cd backend && uv python install 3.12 && uv sync && uv run uvicorn app.main:create_app --factory --reload

# Frontend (Vite + React)
cd frontend && npm install && npm run dev   # Dev server proxies /api to localhost:8000
```

- **Database Migrations**: `docker compose -f deploy/docker-compose.yml exec app alembic upgrade head`
- **Type Safety**: Strictly typed with TypeScript and Python Type Hints. Production code disallows `as any`.

---

## Testing & Verification

```bash
# Backend unit & integration tests
cd backend && uv run pytest

# Frontend tests & type checking
cd frontend && npx vitest run
```

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md): Living architectural contract, secrets policies, write pipeline design, and PII lifecycle.
- [`docs/runbook.md`](docs/runbook.md): Operations runbook, backup/restore procedures, and complete environment variable references.
- [`docs/launch-checklist.md`](docs/launch-checklist.md): Pre-launch verification gates and state machine requirements.
- [`docs/verified-facts.md`](docs/verified-facts.md): Documented behaviors, endpoint quirks, and error parsing rules live-verified against the university system.

---

## Recent Highlights

- **Full Bilingual UI**: Custom zero-dependency i18n support with an instant language toggle in the navigation bar.
- **Accurate Error Parsing**: The records view captures verbatim failure reasons directly from the school system (such as prerequisite or restriction violations) with student ID masking.
- **Reliable PNG Export**: Upgraded export engine to `html2canvas` with rendered canvas integrity checks for crisp timetable images.
- **Unified Console Experience**: Integrated course search, weekly timetable visualization, staging list, and write status into a single cohesive interface.

---

## Attribution & License

Adapted from and inspired by the following open-source projects:

- [NSYSU-OpenDev/NSYSUCourseAPI](https://github.com/NSYSU-OpenDev/NSYSUCourseAPI) — Course catalog schema and parsing
- [NSYSU-OpenDev/NSYSUSelectorHelper](https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper) — Timetable grid layout and timeslot conflict logic
- [edwinchu0711/NsysuApp_OpenSource](https://github.com/edwinchu0711/NsysuApp_OpenSource) — SSO2 login workflow and selection service behavior
- [nsysu-code-club/NSYSU-AP](https://github.com/nsysu-code-club/NSYSU-AP) — SSO2 authentication reference
- [Hua777/NSYSUSelcrs](https://github.com/Hua777/NSYSUSelcrs) — System architecture reference
