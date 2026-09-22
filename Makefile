.PHONY: up down logs import test test-pg lint fmt lock build

up:            ## run the site at http://localhost:8787 (SQLite in ./data, reloads on src changes)
	docker compose up -d app

down:
	docker compose down --remove-orphans

logs:
	docker compose logs -f app

import:        ## import the example documents (idempotent)
	docker compose run --rm import

build:
	docker compose build app test lint

test:          ## pytest in a container (SQLite)
	docker compose build test
	docker compose run --rm --no-deps test

test-pg:       ## pytest in a container, contract tests also against PostgreSQL
	docker compose build test
	docker compose run --rm test-pg; status=$$?; docker compose rm -sf postgres >/dev/null; exit $$status

lint:          ## black --check / isort --check-only / ruff, in a container
	docker compose build lint
	docker compose run --rm --no-deps lint

fmt:           ## format in place
	docker compose build lint
	docker compose run --rm --no-deps --entrypoint sh lint -c "uv run black packages && uv run isort packages"

lock:          ## regenerate uv.lock after changing dependencies
	docker run --rm -v "$(PWD)":/app -w /app ghcr.io/astral-sh/uv:python3.11-bookworm-slim uv lock
