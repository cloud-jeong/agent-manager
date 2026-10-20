# Agent Manager

A standalone **FastAPI + Next.js** reimplementation of [Archestra](https://github.com/archestra-ai/archestra)'s agent management: agent CRUD, team/organization visibility, labels, soft delete/restore, and a per-user default agent.

Docs:
- [`docs/plan.md`](docs/plan.md): design plan and the Archestra code each part was ported from
- [`docs/data-model.md`](docs/data-model.md): ERD, domain objects, API models, frontend state
- [`docs/sequence-diagrams.md`](docs/sequence-diagrams.md): sequence diagrams for each flow (auth, list, create, update, delete/restore, labels, default agent, teams)

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + asyncpg, Alembic, JWT (pyjwt + bcrypt), uv, ruff, pytest |
| Frontend | Next.js 16 (App Router), React 19, TanStack Query v5, react-hook-form + zod, shadcn/ui (Base UI) + Tailwind v4, openapi-fetch + openapi-typescript |
| Infra | PostgreSQL 16, docker compose |

## Quick start (docker)

```bash
cp .env.example .env            # optional
make up                         # postgres + backend (:8000, runs migrations) + frontend (:3000)
docker compose exec backend python -m app.seed
```

If port 3000 is taken on your machine, run `FRONTEND_PORT=3100 make up` and open http://localhost:3100. CORS follows the same variable.

Seed users (all with password `password123`):

| User | Org role | Teams |
|---|---|---|
| admin@example.com | admin | — |
| alice@example.com | member | Engineering (team admin) |
| bob@example.com | member | Engineering (member), Support (team admin) |

API docs: http://localhost:8000/docs

## Local development

```bash
make db             # only Postgres in docker (host port 5433)
make migrate        # alembic upgrade head
make seed
make dev-backend    # uvicorn --reload on :8000
make dev-frontend   # next dev on :3000
```

Other commands:

```bash
make test       # backend tests against the agent_manager_test database
make lint       # ruff + eslint
make gen-api    # regenerate frontend/src/lib/api/schema.d.ts from the FastAPI OpenAPI schema
```

After changing a backend request/response schema, run `make gen-api` so the frontend types stay in sync.
After changing ORM models, create a migration: `cd backend && uv run alembic revision --autogenerate -m "..."`.

## Access model

Ported from Archestra (`findAccessibleIdsForUser`, `requireAgentModifyPermission`):

| Scope | Who can see it | Who can edit/delete it |
|---|---|---|
| `personal` | author, users it is shared with, admins | author, users shared with `write` level, admins |
| `team` | members of any assigned team, admins | team admins of an assigned team, admins |
| `org` | everyone | admins |

Other rules:
- Only admins can create or convert agents to `org`.
- Non-admins may only add or remove teams they administer; other teams stay assigned.
- A shared (`team`/`org`) agent cannot be made `personal` again.
- Editing an agent you can't modify returns **404**, not 403, so its existence isn't revealed.
- Delete is a soft delete. Deleted agents are listed with `status=deleted` (only to users who could restore them). Restoring fails with 409 if an active agent has the same name. Permanent delete requires a soft delete first.
- Deleting an agent clears every user's default-agent pin pointing at it.
- Labels: one value per key per agent. The list filter `labels=k1:v1|v2;k2:v3` means AND across keys, OR within a key's values.

Errors always have the shape `{"error": {"message": "...", "type": "api_validation_error" | ...}}`.

## Layout

```
backend/
  app/models/         SQLAlchemy ORM
  app/schemas/        Pydantic request/response models (camelCase on the wire)
  app/repositories/   all database access
  app/services/       business rules (access.py = visibility/modify rules, agent.py = agent workflows)
  app/api/            FastAPI routers
  alembic/            migrations
  tests/              pytest (real Postgres, tables truncated between tests)
frontend/src/
  app/                thin route files
  components/agents/  list page, table, toolbar, form, visibility selector, labels editor
  components/settings teams & users admin page
  lib/api/            typed client (generated schema.d.ts + openapi-fetch)
  lib/queries/        TanStack Query hooks
```
