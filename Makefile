.PHONY: setup lint test lint-api lint-worker lint-web test-api test-worker test-web

setup:
	cd apps/api && uv sync
	cd apps/worker && uv sync
	pnpm --dir apps/web install
	pre-commit install

lint: lint-api lint-worker lint-web

lint-api:
	cd apps/api && uv run ruff check .
	cd apps/api && uv run black --check .
	cd apps/api && uv run mypy --strict app tests

lint-worker:
	cd apps/worker && uv run ruff check .
	cd apps/worker && uv run black --check .
	cd apps/worker && uv run mypy --strict worker tests

lint-web:
	pnpm --dir apps/web exec prettier --check .
	pnpm --dir apps/web exec eslint . --max-warnings=0
	pnpm --dir apps/web exec tsc --noEmit

test: test-api test-worker test-web

test-api:
	cd apps/api && uv run pytest

test-worker:
	cd apps/worker && uv run pytest

test-web:
	pnpm --dir apps/web test
