.PHONY: install test test-integration lint i18n db-up db-down simuler servir

DSN ?= postgresql://ballan:ballan@localhost:5433/ballan_test

install:
	python -m pip install -r requirements/serveur.lock -e ".[dev]"

# Suite complete, sans base de donnees ni reseau.
test:
	python -m pytest -q

# Exige un PostgreSQL jetable : make db-up d'abord.
test-integration:
	BALLAN_TEST_DSN="$(DSN)" python -m pytest tests/integration -q

lint:
	python -m ruff check .

# Completude des traductions — sort 1 si une langue est incomplete.
i18n:
	python -m core.i18n.rapport

db-up:
	docker compose -f docker/docker-compose.dev.yml up -d --wait

db-down:
	docker compose -f docker/docker-compose.dev.yml down -v

# Conversation de demonstration, sans WhatsApp ni base.
simuler:
	python -m application simuler

# API en mode demonstration (memoire), sur http://localhost:8000
servir:
	python -m application servir --hote 127.0.0.1 --port 8000
