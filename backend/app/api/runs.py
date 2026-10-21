import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentActor, DbSession
from app.db import SessionLocal
from app.pubsub import RUN_EVENTS, Notifier, wait
from app.repositories import run as run_repo
from app.repositories import run_event as run_event_repo
from app.repositories.run import RunListFilters
from app.schemas.common import Paginated
from app.schemas.runtime import (
    TERMINAL_RUN_STATUSES,
    RunCreate,
    RunDetail,
    RunRead,
    RunStatus,
    RunTrigger,
)
from app.services import conversation as conversation_service

router = APIRouter(prefix="/api", tags=["runs"])

# Shared by every SSE stream served by this process.
run_events_notifier = Notifier(RUN_EVENTS)

# Re-check the database at least this often, in case a notification was missed.
_POLL_SECONDS = 2.0
# Send a comment line this often so proxies keep idle streams open.
_KEEPALIVE_SECONDS = 15.0


@router.post(
    "/agents/{agent_id}/runs",
    response_model=RunRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="startRun",
)
async def start_run(
    agent_id: uuid.UUID, body: RunCreate, actor: CurrentActor, db: DbSession
) -> RunRead:
    """Run the agent on `input` in a new conversation. Poll `GET /api/runs/{id}` for the result."""
    return await conversation_service.start_run(db, actor, agent_id, body.input)


@router.get("/runs", response_model=Paginated[RunRead], operation_id="listRuns")
async def list_runs(
    actor: CurrentActor,
    db: DbSession,
    run_status: RunStatus | None = Query(default=None, alias="status"),
    agent_id: uuid.UUID | None = Query(default=None, alias="agentId"),
    trigger: RunTrigger | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Paginated[RunRead]:
    filters = RunListFilters(
        status=run_status, agent_id=agent_id, trigger=trigger, limit=limit, offset=offset
    )
    return await conversation_service.list_runs(db, actor, filters)


@router.get("/runs/{run_id}", response_model=RunDetail, operation_id="getRun")
async def get_run(run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> RunDetail:
    return await conversation_service.get_run(db, actor, run_id)


@router.post("/runs/{run_id}/cancel", response_model=RunRead, operation_id="cancelRun")
async def cancel_run(run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> RunRead:
    return await conversation_service.cancel_run(db, actor, run_id)


@router.get(
    "/runs/{run_id}/events",
    operation_id="streamRunEvents",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    actor: CurrentActor,
    db: DbSession,
    after: int | None = Query(default=None, description="Only events with a greater seq"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """Server-sent events for a run. Each event's `id` is its seq; reconnect with
    `Last-Event-ID` (or `?after=`) to resume. The stream ends with a `done` event."""
    await conversation_service.get_owned_run(db, actor, run_id)
    start = after if after is not None else _parse_seq(last_event_id)
    return StreamingResponse(
        _event_stream(run_id, start, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _event_stream(run_id: uuid.UUID, after: int, request: Request) -> AsyncIterator[str]:
    last_seq = after
    idle = 0.0
    async with run_events_notifier.subscribe(str(run_id)) as notified:
        while True:
            async with SessionLocal() as db:
                # Read the status before the events so no event written before
                # the run finished can be missed.
                run = await run_repo.get(db, run_id)
                events = await run_event_repo.list_after(db, run_id, last_seq)
            for event in events:
                last_seq = event.seq
                yield _format(event.type, event.data, event_id=event.seq)
            if events:
                idle = 0.0
                continue
            if run is None or run.status in TERMINAL_RUN_STATUSES:
                yield _format("done", {"status": run.status if run else "deleted"})
                return
            if await request.is_disconnected():
                return
            if not await wait(notified, _POLL_SECONDS):
                idle += _POLL_SECONDS
                if idle >= _KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"


def _format(event_type: str, data: object, *, event_id: int | None = None) -> str:
    lines = [f"id: {event_id}"] if event_id is not None else []
    lines += [f"event: {event_type}", f"data: {json.dumps(data, ensure_ascii=False)}"]
    return "\n".join(lines) + "\n\n"


def _parse_seq(value: str | None) -> int:
    try:
        return int(value) if value is not None else -1
    except ValueError:
        return -1
