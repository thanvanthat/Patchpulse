COMPOSE ?= docker compose
RUN := $(COMPOSE) exec -T api

.PHONY: up down migrate seed-demo test lint logs

up:  ## Build and start db, redis, api, worker
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

migrate:
	$(RUN) alembic upgrade head

seed-demo:  ## Generate fixtures/demo_game and load releases + commits
	$(RUN) python -m scripts.seed_demo

test:
	$(RUN) pytest -q

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy .

logs:
	$(COMPOSE) logs -f api worker
