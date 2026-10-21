import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Run
from app.pubsub import RUN_QUEUED


@dataclass
class RunListFilters:
    status: str | None = None
    agent_id: uuid.UUID | None = None
    trigger: str | None = None
    limit: int = 20
    offset: int = 0


async def create(
    db: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    trigger: str,
) -> Run:
    run = Run(conversation_id=conversation_id, agent_id=agent_id, user_id=user_id, trigger=trigger)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    # Delivered on commit; wakes up idle workers.
    await db.execute(text("SELECT pg_notify(:channel, '')"), {"channel": RUN_QUEUED})
    return run


async def get(db: AsyncSession, run_id: uuid.UUID) -> Run | None:
    return await db.get(Run, run_id, populate_existing=True)


async def get_owned(db: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID) -> Run | None:
    return await db.scalar(select(Run).where(Run.id == run_id, Run.user_id == user_id))


async def get_active_for_conversations(
    db: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Run]:
    if not conversation_ids:
        return {}
    stmt = select(Run).where(
        Run.conversation_id.in_(conversation_ids), Run.status.in_(("queued", "running"))
    )
    return {r.conversation_id: r for r in await db.scalars(stmt)}


async def list_for_user(
    db: AsyncSession, user_id: uuid.UUID, filters: RunListFilters
) -> tuple[list[Run], int]:
    conds = [Run.user_id == user_id]
    if filters.status:
        conds.append(Run.status == filters.status)
    if filters.agent_id:
        conds.append(Run.agent_id == filters.agent_id)
    if filters.trigger:
        conds.append(Run.trigger == filters.trigger)
    total = await db.scalar(select(func.count()).select_from(Run).where(*conds)) or 0
    stmt = (
        select(Run)
        .where(*conds)
        .order_by(Run.created_at.desc(), Run.id)
        .limit(filters.limit)
        .offset(filters.offset)
    )
    return list(await db.scalars(stmt)), total


async def claim_next(db: AsyncSession) -> uuid.UUID | None:
    """Move the oldest queued run to `running`; concurrent workers skip each other's rows."""
    next_id = (
        select(Run.id)
        .where(Run.status == "queued")
        .order_by(Run.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    now = datetime.now(UTC)
    return await db.scalar(
        update(Run)
        .where(Run.id == next_id)
        .values(status="running", started_at=now, heartbeat_at=now)
        .returning(Run.id)
    )


async def heartbeat(db: AsyncSession, run_id: uuid.UUID) -> bool:
    """Record that the run is alive; returns whether cancellation was requested."""
    return bool(
        await db.scalar(
            update(Run)
            .where(Run.id == run_id)
            .values(heartbeat_at=datetime.now(UTC))
            .returning(Run.cancel_requested)
        )
    )


async def request_cancel(db: AsyncSession, run: Run) -> None:
    if run.status == "queued":
        # Not picked up yet: no worker will see it, so finish it here.
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
    run.cancel_requested = True
    await db.flush()


async def add_usage(
    db: AsyncSession,
    run_id: uuid.UUID,
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int,
) -> None:
    await db.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
            model=model,
            input_tokens=Run.input_tokens + input_tokens,
            output_tokens=Run.output_tokens + output_tokens,
            cache_read_input_tokens=Run.cache_read_input_tokens + cache_read_input_tokens,
        )
    )


async def finish(db: AsyncSession, run_id: uuid.UUID, *, status: str, error: str | None) -> bool:
    """Mark a running run finished. Returns False if it was already finished elsewhere."""
    finished = await db.scalar(
        update(Run)
        .where(Run.id == run_id, Run.status == "running")
        .values(status=status, error=error, finished_at=datetime.now(UTC))
        .returning(Run.id)
    )
    return finished is not None


async def find_stale(db: AsyncSession, older_than_seconds: int) -> list[uuid.UUID]:
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    stmt = select(Run.id).where(Run.status == "running", Run.heartbeat_at < cutoff)
    return list(await db.scalars(stmt))
