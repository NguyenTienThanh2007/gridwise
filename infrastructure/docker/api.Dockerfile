# syntax=docker/dockerfile:1
# Build context: repository root.
FROM python:3.15-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Dependencies first, so source edits do not invalidate this layer.
COPY pyproject.toml uv.lock .python-version ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package gridwise-api

COPY apps/api apps/api
RUN uv sync --frozen --no-dev --no-editable --package gridwise-api


FROM python:3.15-slim AS runtime
RUN useradd --system --uid 10001 --no-create-home gridwise
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
USER gridwise
EXPOSE 8000
CMD ["uvicorn", "--factory", "gridwise_api.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
