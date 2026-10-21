import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunEvent
from app.pubsub import RUN_EVENTS


async def append(
    db: AsyncSession, run_id: uuid.UUID, events: list[tuple[int, str, dict[str, Any]]]
) -> None:
    """Insert `(seq, type, data)` events and notify listeners of this run (on commit)."""
    if not events:
        return
    db.add_all(
        RunEvent(run_id=run_id, seq=seq, type=type_, data=data) for seq, type_, data in events
    )
    await db.flush()
    await db.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": RUN_EVENTS, "payload": str(run_id)},
    )


async def next_seq(db: AsyncSession, run_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.coalesce(func.max(RunEvent.seq) + 1, 0)).where(RunEvent.run_id == run_id)
    )


async def list_after(
    db: AsyncSession, run_id: uuid.UUID, after_seq: int, limit: int = 500
) -> list[RunEvent]:
    stmt = (
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
        .order_by(RunEvent.seq)
        .limit(limit)
    )
    return list(await db.scalars(stmt))
