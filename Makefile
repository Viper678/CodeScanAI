.PHONY: setup lint test lint-api lint-worker lint-web test-api test-worker test-web \
	e2e e2e-ui e2e-up e2e-down e2e-fixtures dev dev-down

UV ?= uv

# Compose stack used by the e2e suite (T5.5). NOT the dev overrides — the
# stock images run without host-volume mounts so Next.js doesn't reload
# while the spec is exercising the UI. ``-p codescan-e2e`` isolates the
# containers and named volumes (pgdata, data) from a dev stack running
# in the same checkout — without it, ``e2e-down -v`` wipes the
# developer's local DB and uploads.
#
# Post-split: backend (api + worker + postgres + redis) and frontend
# (web) live in separate per-repo compose files. Chaining all four under
# the same ``-p`` project name puts them on a single compose network so
# the web container resolves ``api`` over compose DNS.
E2E_COMPOSE := docker compose -p codescan-e2e \
	-f codescan-backend/docker-compose.yml \
	-f codescan-backend/docker-compose.e2e.yml \
	-f codescan-frontend/docker-compose.yml \
	-f codescan-frontend/docker-compose.e2e.yml

# Compose interpolates required substitutions BEFORE merging override
# files, so the base ``codescan-backend/docker-compose.yml``'s
# ``JWT_SECRET`` needs a value up front. Without this default,
# ``make e2e-down`` (and ``ps`` and ``logs``) fail for a developer who
# hasn't exported it. The LLM endpoint vars have ``:-`` defaults in the
# compose file so no injection is needed for them.
E2E_ENV := JWT_SECRET=$${JWT_SECRET:-e2e-jwt-secret-32-bytes-long-padding}

# Web base URL used by the Playwright suite. Matches the alt host port
# pinned in ``codescan-frontend/docker-compose.e2e.yml`` so the e2e
# stack coexists with a dev stack on 3000. Override via
# ``E2E_WEB_BASE_URL=…`` in the env if you've remapped the port.
E2E_WEB_BASE_URL ?= http://localhost:3010

setup:
	cd codescan-backend/api && $(UV) sync --locked
	cd codescan-backend/worker && $(UV) sync --locked
	pnpm --dir codescan-frontend install
	pre-commit install

# Bring up the full local dev stack — backend (api + worker + postgres +
# redis) first so its api service is healthy before the frontend pings
# it through ``INTERNAL_API_URL``. Each subdir has its own compose
# project name so the stacks stay independently teardown-able.
dev:
	cd codescan-backend && docker compose up -d --build
	cd codescan-frontend && docker compose up -d --build

dev-down:
	cd codescan-frontend && docker compose down
	cd codescan-backend && docker compose down

lint: lint-api lint-worker lint-web

lint-api:
	cd codescan-backend/api && $(UV) sync --locked
	cd codescan-backend/api && .venv/bin/ruff check .
	cd codescan-backend/api && .venv/bin/black --check .
	cd codescan-backend/api && .venv/bin/mypy --strict app tests

lint-worker:
	cd codescan-backend/worker && $(UV) sync --locked
	cd codescan-backend/worker && .venv/bin/ruff check .
	cd codescan-backend/worker && .venv/bin/black --check .
	cd codescan-backend/worker && .venv/bin/mypy --strict worker tests

lint-web:
	pnpm --dir codescan-frontend exec prettier --check .
	pnpm --dir codescan-frontend exec eslint . --max-warnings=0
	pnpm --dir codescan-frontend exec tsc --noEmit

test: test-api test-worker test-web

test-api:
	cd codescan-backend/api && $(UV) sync --locked
	cd codescan-backend/api && .venv/bin/pytest

test-worker:
	cd codescan-backend/worker && $(UV) sync --locked
	cd codescan-backend/worker && .venv/bin/pytest

test-web:
	pnpm --dir codescan-frontend test

# Build the deterministic sample zip used by the Playwright suite. Idempotent.
e2e-fixtures:
	python3 codescan-frontend/e2e/fixtures/build_sample_zip.py

# Bring the full e2e stack up (api + worker + web + postgres + redis) with
# LLM_MOCK_MODE=true. ``--wait`` blocks until every service reports
# ``healthy``, so when this returns the stack is ready for Playwright.
e2e-up:
	$(E2E_ENV) $(E2E_COMPOSE) up -d --build --wait
	$(E2E_ENV) $(E2E_COMPOSE) ps

# Tear down + delete the e2e volumes (postgres data + uploads). Safe to
# call repeatedly; idempotent and doesn't touch the dev stack.
e2e-down:
	$(E2E_ENV) $(E2E_COMPOSE) down -v --remove-orphans

# Headless run — what CI uses. Self-contained: brings the e2e stack up
# (idempotent) and runs ``pnpm install`` so the playwright binary
# resolves on a host that's only ever run docker (host node_modules
# would otherwise be empty since the dev override mounts them as a
# named volume inside the container).
e2e: e2e-fixtures e2e-up
	pnpm --dir codescan-frontend install
	pnpm --dir codescan-frontend exec playwright install --with-deps chromium
	E2E_WEB_BASE_URL=$(E2E_WEB_BASE_URL) pnpm --dir codescan-frontend exec playwright test

# Headed / interactive UI mode for local development. The slowMo configured
# in playwright.config.ts makes the journey readable in real time.
e2e-ui: e2e-fixtures e2e-up
	pnpm --dir codescan-frontend install
	pnpm --dir codescan-frontend exec playwright install chromium
	E2E_WEB_BASE_URL=$(E2E_WEB_BASE_URL) pnpm --dir codescan-frontend exec playwright test --ui
