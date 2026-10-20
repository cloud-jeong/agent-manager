.PHONY: up down db migrate seed test lint dev-backend dev-frontend gen-api

up:
	docker compose up -d --build

down:
	docker compose down

# Start only Postgres (for local development without containers for the apps)
db:
	docker compose up -d postgres

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.seed

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && pnpm lint

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && pnpm dev

# Regenerate the typed frontend API client from the backend OpenAPI schema
gen-api:
	cd backend && uv run python -m app.export_openapi > ../frontend/openapi.json
	cd frontend && pnpm gen:api
