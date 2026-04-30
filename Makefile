.PHONY: setup lint test lint-api lint-worker lint-web test-api test-worker test-web

UV ?= uv

setup:
	cd apps/api && $(UV) sync --locked
	cd apps/worker && $(UV) sync --locked
	pnpm --dir apps/web install
	pre-commit install

lint: lint-api lint-worker lint-web

lint-api:
	cd apps/api && $(UV) sync --locked
	cd apps/api && .venv/bin/ruff check .
	cd apps/api && .venv/bin/black --check .
	cd apps/api && .venv/bin/mypy --strict app tests

lint-worker:
	cd apps/worker && $(UV) sync --locked
	cd apps/worker && .venv/bin/ruff check .
	cd apps/worker && .venv/bin/black --check .
	cd apps/worker && .venv/bin/mypy --strict worker tests

lint-web:
	pnpm --dir apps/web exec prettier --check .
	pnpm --dir apps/web exec eslint . --max-warnings=0
	pnpm --dir apps/web exec tsc --noEmit

test: test-api test-worker test-web

test-api:
	cd apps/api && $(UV) sync --locked
	cd apps/api && .venv/bin/pytest

test-worker:
	cd apps/worker && $(UV) sync --locked
	cd apps/worker && .venv/bin/pytest

test-web:
	pnpm --dir apps/web test
