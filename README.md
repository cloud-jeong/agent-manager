# Agent Manager

A standalone **FastAPI + Next.js** reimplementation of [Archestra](https://github.com/archestra-ai/archestra)'s agent management: agent CRUD, team/organization visibility, labels, soft delete/restore, and a per-user default agent.

Registered agents can also be **run**: chat with them in the browser, or start runs through the API. Runs execute on a background worker that calls Claude, runs bash and file editor tools in a per-conversation sandbox container, and can use web search/fetch and remote MCP servers.

Docs:
- [`docs/plan.md`](docs/plan.md): design plan and the Archestra code each part was ported from
- [`docs/runtime-plan.md`](docs/runtime-plan.md): design of the execution environment (runs, worker, sandbox, MCP)
- [`docs/data-model.md`](docs/data-model.md): ERD, domain objects, API models, frontend state
- [`docs/sequence-diagrams.md`](docs/sequence-diagrams.md): sequence diagrams for each flow (auth, list, create, update, delete/restore, labels, default agent, teams)

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + asyncpg, Alembic, JWT (pyjwt + bcrypt), uv, ruff, pytest |
| Frontend | Next.js 16 (App Router), React 19, TanStack Query v5, react-hook-form + zod, shadcn/ui (Base UI) + Tailwind v4, openapi-fetch + openapi-typescript |
| Runtime | Anthropic Python SDK (Messages API, streaming), Postgres-backed run queue (`FOR UPDATE SKIP LOCKED` + `LISTEN/NOTIFY`), Docker sandboxes (docker SDK), SSE |
| Infra | PostgreSQL 16, docker compose |

## Quick start (docker)

```bash
cp .env.example .env            # set ANTHROPIC_API_KEY to run agents
make up                         # sandbox image + postgres + backend (:8000, runs migrations)
                                # + worker + frontend (:3000)
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
make dev-worker     # executes runs (needs ANTHROPIC_API_KEY in backend/.env or the environment)
make dev-frontend   # next dev on :3000
make sandbox-image  # build the sandbox image used by the bash and file editor tools
```

Other commands:

```bash
make test       # backend tests against the agent_manager_test database
                # (sandbox tests also run when Docker and the sandbox image are available)
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

## Running agents

- **Chat** (`/chat`): pick an agent and send a message. The response streams in, including the model's summarized thinking and tool calls. Conversations are private to their author.
- **API**: `POST /api/agents/{id}/runs` with `{"input": "..."}` returns `202` and a run; poll `GET /api/runs/{id}` for `status` and `output`, or follow `GET /api/runs/{id}/events` (SSE). `POST /api/runs/{id}/cancel` stops a run.
- **History** (`/runs`): every run with status, tokens and duration.
- Anyone who can **see** an agent can run it. Agents of type `mcp_gateway` and deleted agents cannot be run.

Per-agent runtime settings (agent form → Runtime): model (default `claude-opus-5-5`), effort, max turns per run, tools (bash, file editor, web search, web fetch), sandbox network access, and MCP servers.

How it works:
- The API stores the user message and a `queued` run, then returns. A worker process claims the run from Postgres (`FOR UPDATE SKIP LOCKED`), runs the agent loop against the Claude API, and writes progress to `run_events`. Clients stream those events over SSE and can reconnect with `Last-Event-ID`.
- The transcript is append-only: assistant content is stored exactly as returned and replayed unchanged.
- Workers send heartbeats; a run whose worker disappears is marked failed after 60 seconds. Runs are not retried automatically.
- Requests opt into the server-side refusal fallback (`fallbacks: "default"`) except on Claude Haiku 5.5, which has none.

### Sandbox

The bash and file editor tools run in a Docker container per conversation (`agent-sandbox-<id>`). The container gets a persistent `/workspace` volume, an unprivileged user, all capabilities dropped, a read-only root filesystem, memory/CPU/process limits, a 120 s command timeout, and **no network** unless the agent enables it. Idle containers stop after 30 minutes; deleting a conversation removes its container and volume.

> **Security:** the worker needs the Docker socket, which is root-equivalent on the host. That is fine for local development. For production, run sandboxes under gVisor (`AGENT_MANAGER_SANDBOX_RUNTIME=runsc`) or on a separate host.

### MCP servers

Admins register remote MCP servers at `/settings/mcp-servers` (HTTPS only; Claude connects to them from Anthropic's servers). Tokens are encrypted with `AGENT_MANAGER_SECRET_KEY` and never returned by the API. Agents opt in to servers in their Runtime settings.

Errors always have the shape `{"error": {"message": "...", "type": "api_validation_error" | ...}}`.

## Layout

```
docker/sandbox/       image for sandbox containers
backend/
  app/models/         SQLAlchemy ORM
  app/schemas/        Pydantic request/response models (camelCase on the wire)
  app/repositories/   all database access
  app/services/       business rules (access.py = visibility/modify rules, agent.py = agent workflows,
                      conversation.py = conversations and runs)
  app/services/runtime/  agent loop (executor.py), Claude client (llm.py), tools.py, sandbox.py, events.py
  app/worker.py       background worker: claims runs, heartbeats, reaps stale runs and idle sandboxes
  app/api/            FastAPI routers
  alembic/            migrations
  tests/              pytest (real Postgres, tables truncated between tests)
frontend/src/
  app/                thin route files
  components/agents/  list page, table, toolbar, form, visibility selector, labels editor
  components/chat/    chat pages, message rendering, live run stream (use-run-stream.ts)
  components/runs/    run history
  components/settings teams & users and MCP server admin pages
  lib/api/            typed client (generated schema.d.ts + openapi-fetch), SSE client (run-events.ts)
  lib/queries/        TanStack Query hooks
```
