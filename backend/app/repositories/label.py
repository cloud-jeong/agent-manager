import uuid
from collections.abc import Iterable

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentLabel, LabelKey, LabelValue


async def sync_agent_labels(
    db: AsyncSession, agent_id: uuid.UUID, labels: list[tuple[str, str]]
) -> None:
    """Replace all labels of an agent, then prune keys/values no agent uses anymore."""
    await db.execute(delete(AgentLabel).where(AgentLabel.agent_id == agent_id))
    rows = []
    for key, value in labels:
        rows.append(
            {
                "agent_id": agent_id,
                "key_id": await _get_or_create_key(db, key),
                "value_id": await _get_or_create_value(db, value),
            }
        )
    if rows:
        await db.execute(insert(AgentLabel), rows)
    await prune_orphans(db)


async def prune_orphans(db: AsyncSession) -> None:
    await db.execute(delete(LabelKey).where(~LabelKey.id.in_(select(AgentLabel.key_id).distinct())))
    await db.execute(
        delete(LabelValue).where(~LabelValue.id.in_(select(AgentLabel.value_id).distinct()))
    )


async def get_labels_for_agents(
    db: AsyncSession, agent_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[str, str]]]:
    """Batch-load (key, value) per agent, ordered by key."""
    ids = set(agent_ids)
    result: dict[uuid.UUID, list[tuple[str, str]]] = {i: [] for i in ids}
    if not ids:
        return result
    rows = await db.execute(
        select(AgentLabel.agent_id, LabelKey.key, LabelValue.value)
        .join(LabelKey, LabelKey.id == AgentLabel.key_id)
        .join(LabelValue, LabelValue.id == AgentLabel.value_id)
        .where(AgentLabel.agent_id.in_(ids))
        .order_by(LabelKey.key)
    )
    for r in rows:
        result[r.agent_id].append((r.key, r.value))
    return result


async def get_all_keys(db: AsyncSession) -> list[str]:
    return list(await db.scalars(select(LabelKey.key).order_by(LabelKey.key)))


async def get_values(db: AsyncSession, key: str | None = None) -> list[str]:
    """All label values, or only the values used with `key`."""
    if key is None:
        return list(await db.scalars(select(LabelValue.value).order_by(LabelValue.value)))
    stmt = (
        select(LabelValue.value)
        .join(AgentLabel, AgentLabel.value_id == LabelValue.id)
        .join(LabelKey, LabelKey.id == AgentLabel.key_id)
        .where(LabelKey.key == key)
        .distinct()
        .order_by(LabelValue.value)
    )
    return list(await db.scalars(stmt))


# =============================================================================
# Internal helpers
# =============================================================================


async def _get_or_create_key(db: AsyncSession, key: str) -> uuid.UUID:
    await db.execute(pg_insert(LabelKey).values(key=key).on_conflict_do_nothing())
    return await db.scalar(select(LabelKey.id).where(LabelKey.key == key))


async def _get_or_create_value(db: AsyncSession, value: str) -> uuid.UUID:
    await db.execute(pg_insert(LabelValue).values(value=value).on_conflict_do_nothing())
    return await db.scalar(select(LabelValue.id).where(LabelValue.value == value))
