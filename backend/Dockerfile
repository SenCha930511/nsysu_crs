FROM ghcr.io/astral-sh/uv:0.9.26-python3.12-bookworm-slim

# TZ pinned site-wide; bookworm-slim ships without tzdata.
ENV TZ=Asia/Taipei \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home app

WORKDIR /app
RUN chown app:app /app

# Dependency layer first for build-cache efficiency; uv.lock pins everything.
COPY --chown=app:app pyproject.toml uv.lock ./
USER app
RUN uv sync --locked --no-dev --no-install-project

COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
