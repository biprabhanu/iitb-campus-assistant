# CampusPilot hosted API. Build context is the REPO ROOT:
#   docker build -f apps/api/Dockerfile -t campuspilot-api .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Layout mirrors the repo so REPO_ROOT (parents[3] of config.py) is /app.
WORKDIR /app/apps/api

# Dependencies first (cached unless the lock changes). The project itself is not installed:
# the package is imported from the source tree (PYTHONPATH below).
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/campuspilot ./campuspilot
COPY data/sources/registry.csv /app/data/sources/registry.csv
COPY data/fixtures /app/data/fixtures

RUN useradd --system --uid 10001 --no-create-home campuspilot \
    && mkdir -p /tmp/raw && chown -R campuspilot /tmp/raw
USER campuspilot

ENV PYTHONPATH=/app/apps/api \
    DEPLOY_MODE=hosted \
    INDEX_SOURCE=release \
    CAMPUSPILOT_DB_PATH=/tmp/campuspilot.db \
    CAMPUSPILOT_RAW_DIR=/tmp/raw \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8000'),timeout=4)"

CMD ["sh", "-c", "exec uvicorn campuspilot.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
