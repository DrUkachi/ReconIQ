.PHONY: up down logs migrate seed reset-demo test demo-check ddl fmt

up:
	docker compose up -d --build
	@echo "Waiting for the database..."
	@until docker compose exec -T db pg_isready -U bankrecon >/dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	@echo "API on http://localhost:8000 — docs at /docs"

down:
	docker compose down

logs:
	docker compose logs -f api worker

# PRD section 21: migrations are an explicit step, never automatic on boot.
migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python -m scripts.seed

reset-demo:
	docker compose run --rm api python -m scripts.seed --reset

test:
	python -m pytest -q

# PRD section 21: run immediately before presenting. Green output or a named failure.
demo-check:
	python -m scripts.demo_check

ddl:
	python scripts/generate_ddl.py

fmt:
	python -m ruff format app tests scripts 2>/dev/null || true
