# GridPulse — common dev commands.
# `make help` to list them.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# ---- Setup ---------------------------------------------------------------

.PHONY: install
install: ## Create venv and install all deps (core + ingestion + dev)
	uv sync --all-groups

.PHONY: env
env: ## Copy .env.example -> .env if .env doesn't exist
	@test -f .env || (cp .env.example .env && echo "Created .env (edit me)")

# ---- Code quality --------------------------------------------------------

.PHONY: fmt
fmt: ## Auto-format with ruff
	uv run ruff format .
	uv run ruff check --fix .

.PHONY: lint
lint: ## Check formatting + lint (no fixes)
	uv run ruff format --check .
	uv run ruff check .

.PHONY: type
type: ## Static type-check with mypy
	uv run mypy gridpulse/

.PHONY: test
test: ## Run unit tests
	uv run pytest -v

.PHONY: test-int
test-int: ## Run integration tests (need a running Postgres)
	uv run pytest -v -m integration

.PHONY: check
check: lint type test ## Run lint + type + test (what CI runs)

# ---- Docker Compose ------------------------------------------------------

.PHONY: up
up: ## Bring up all services in the background
	docker compose up -d

.PHONY: up-db
up-db: ## Just the database — useful when running app in a venv
	docker compose up -d postgres

.PHONY: down
down: ## Stop services (keeps volumes)
	docker compose down

.PHONY: nuke
nuke: ## Stop services AND delete volumes (DESTRUCTIVE)
	docker compose down -v

.PHONY: logs
logs: ## Tail container logs
	docker compose logs -f --tail=100

.PHONY: psql
psql: ## Open a psql shell in the postgres container
	docker compose exec postgres psql -U gridpulse

.PHONY: migrate
migrate: ## Apply database migrations
	uv run python -m gridpulse.storage.migrate

# ---- Deploy --------------------------------------------------------------

.PHONY: deploy-check
deploy-check: ## Validate the merged Compose config (catches syntax errors)
	docker compose -f docker-compose.yml -f docker-compose.prod.yml config

# ---- Help ----------------------------------------------------------------

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
