COMPOSE ?= docker compose
RUN := $(COMPOSE) exec -T api

.PHONY: up down migrate test lint logs

up:  ## Build and start db, redis, api, worker
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

migrate:
	$(RUN) alembic upgrade head

test:
	$(RUN) pytest -q

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy .

logs:
	$(COMPOSE) logs -f api worker
