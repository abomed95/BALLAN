.PHONY: install test test-integration lint i18n db-up db-down

DSN ?= postgresql://ballan:ballan@localhost:5433/ballan_test

install:
	python -m pip install -e ".[dev]"

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
