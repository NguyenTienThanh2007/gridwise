# GRIDWISE developer commands. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

# The root .env holds database credentials, so it is deliberately NOT included or exported
# here: recipes (and the web build in particular) must not inherit them. Each tool reads
# what it needs itself: the API and Alembic through their settings classes, Docker Compose
# natively, and the web app through next.config.ts (public values only).
#
# Only the two port numbers are read, because they are command-line arguments.
# Override either on the command line or from the environment: `make dev-api API_PORT=8030`.
env_value = $(shell sed -n 's/^$(1)=//p' .env 2>/dev/null | tail -n 1)
API_PORT ?= $(or $(call env_value,API_PORT),8020)
WEB_PORT ?= $(or $(call env_value,WEB_PORT),3100)

.PHONY: help setup up up-web down reset-db migrate seed-demo dev-api dev-web fmt lint typecheck \
        test test-engine test-integration test-e2e audit check

help: ## List the available commands
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

setup: ## Create .env if missing and install Python and Node dependencies
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")
	uv sync --locked
	pnpm install --frozen-lockfile

up: ## Start postgres, run migrations and start the API (waits for health)
	docker compose up -d --build --wait

up-web: ## Same as `up`, plus the web app in a container
	docker compose --profile web up -d --build --wait

down: ## Stop the stack (data is kept)
	docker compose --profile web down

reset-db: ## Stop the stack and delete the local database volume
	docker compose --profile web down --volumes

migrate: ## Apply migrations as the owner role (GRIDWISE_MIGRATION_DATABASE_URL)
	cd apps/api && uv run alembic upgrade head

# Source paths are explicit for the same reason as in test-engine (hidden .pth on macOS).
seed-demo: ## Create the synthetic demo organisation and grid (local and test only)
	PYTHONPATH=apps/api/src:packages/grid-engine/src uv run python -m gridwise_api.seed

dev-api: ## Run the API on the host with reload (needs a migrated database)
	uv run uvicorn --app-dir apps/api/src --factory gridwise_api.main:create_app --reload --port $(API_PORT)

dev-web: ## Run the web app on the host with hot reload
	WEB_PORT=$(WEB_PORT) pnpm dev

fmt: ## Format Python and web sources
	uv run ruff format .
	uv run ruff check --fix .
	pnpm format

lint: ## Lint and check formatting (no changes)
	uv run ruff format --check .
	uv run ruff check .
	pnpm format:check
	pnpm lint

typecheck: ## Static type checks
	uv run mypy
	pnpm typecheck

test: ## Unit tests: API, grid engine and web (no services needed)
	uv run pytest -m "not integration"
	pnpm test

# The source path is explicit so the command does not depend on the virtualenv's
# editable-install .pth file, which macOS can hide (docs/development/setup.md, Gotchas).
test-engine: ## Grid engine tests and its closed-form self-check
	uv run pytest packages/grid-engine/tests
	PYTHONPATH=packages/grid-engine/src uv run python -m gridwise_grid_engine.selfcheck

test-integration: ## Database tests; each uses its own throwaway database
	uv run pytest -m integration

test-e2e: ## Browser tests; needs `make up` (builds the web app first)
	pnpm build
	pnpm check:bundle
	WEB_PORT=$(WEB_PORT) pnpm test:e2e

audit: ## Known-vulnerability scan of Python and Node dependencies
	uv export --frozen --no-emit-workspace --format requirements-txt -q \
		| uv run pip-audit --strict --disable-pip --require-hashes -r /dev/stdin
	pnpm audit --audit-level moderate

check: lint typecheck test test-integration ## Everything CI runs except e2e and audit
	pnpm build
	pnpm check:bundle
