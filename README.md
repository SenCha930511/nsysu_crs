# NSYSU Course Wrapper

A monorepo wrapper site around the NSYSU course-selection system: FastAPI backend, Vite + React 18 + TypeScript + Bootstrap 5 frontend, Postgres + Redis, Caddy as the single HTTP entry. Spec and 17-todo work plan: `.omo/plans/nsysu-course-wrapper.md`.

## Hard rule: installs live in venv / containers only

**Every** package install happens inside a virtual environment, a container, or a project directory — never globally:

- Backend: `backend/.venv` via `uv venv` + `uv sync` (Python 3.12 via `uv python install 3.12`; pinned by `backend/uv.lock`).
- Frontend: `frontend/node_modules` via `npm install` / `npm ci`.
- Runtime: everything under `docker compose`.

If a global install ever becomes unavoidable, it must be recorded in `qa/install-log.md` and removed after the task.

## Quickstart

```bash
cp .env.example .env   # fill in APP_SECRET etc. for anything non-local
```

### Prod-ish (static frontend served by Caddy)

```bash
docker compose -f deploy/docker-compose.yml up --build -d
curl -sf http://localhost:8000/api/health   # app direct
curl -sf http://localhost/api/health        # via Caddy
curl -sf http://localhost/                  # frontend page
```

### Dev (hot reload: uvicorn --reload + Vite dev server)

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build
```

Same services (`app`, `worker`, `postgres`, `redis`, `caddy`) plus a `frontend` Vite dev-server service; Postgres/Redis are also published on 5432/6379 for host tooling. The backend bind-mount uses an anonymous `/app/.venv` volume so the in-container Linux venv never fights the host macOS one.

### Local, without Docker (optional convenience)

```bash
cd backend && uv python install 3.12 && uv sync && uv run uvicorn app.main:create_app --factory --reload
cd frontend && npm install && npm run dev   # proxies /api to localhost:8000
```

### Database migrations (Alembic)

```bash
docker compose -f deploy/docker-compose.yml exec app alembic upgrade head    # apply
docker compose -f deploy/docker-compose.yml exec app alembic downgrade base  # roll back
```

Alembic runs inside the `app` container, so `DATABASE_URL` resolves against the compose Postgres with no host port. Autogenerate for later todos: `docker compose -f deploy/docker-compose.yml exec app alembic revision --autogenerate -m "<slug>"`.

### Tests

```bash
cd backend && uv run pytest
```

Credential storage policy (no passwords, selcrs cookies in Redis only): see [`docs/architecture.md`](docs/architecture.md).

TZ is pinned to `Asia/Taipei` everywhere (images + compose env). Redis is pinned to `--maxmemory 128mb --maxmemory-policy noeviction`; volatile-\*/allkeys-\* eviction policies are forbidden for this instance because credential and write-queue keys must never be silently evicted.

## Attribution / licenses

This project adapts logic from the following MIT-licensed projects (file headers carry copyright notices where code is adapted):

- [NSYSU-OpenDev/NSYSUCourseAPI](https://github.com/NSYSU-OpenDev/NSYSUCourseAPI) (MIT) — course catalog field parsing logic.
- [NSYSU-OpenDev/NSYSUSelectorHelper](https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper) (MIT) — weekly timetable grid / timeslot & conflict logic.
- [edwinchu0711/NsysuApp_OpenSource](https://github.com/edwinchu0711/NsysuApp_OpenSource) (MIT) — SSO2 `base64md5` login transform and course-selection service behavior.
- [nsysu-code-club/NSYSU-AP](https://github.com/nsysu-code-club/NSYSU-AP) (MIT) — SSO2 login flow reference.

[Hua777/NSYSUSelcrs](https://github.com/Hua777/NSYSUSelcrs) was used as a **read-only archaeological reference only** — its repository has no LICENSE file, so no code was copied from it.
