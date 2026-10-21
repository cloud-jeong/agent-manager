"""Postgres LISTEN/NOTIFY fan-out.

One asyncpg connection per process listens on a channel and wakes up local waiters.
Notifications are only wake-up hints: the database stays the source of truth, and
waiters re-read it (with a timeout) so a dropped connection only adds latency.
"""

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

# Channel names
RUN_QUEUED = "run_queued"
RUN_EVENTS = "run_events"

# Waiters registered under this key are woken by every notification on the channel.
ANY = "*"


class Notifier:
    def __init__(self, channel: str):
        self.channel = channel
        self._conn: asyncpg.Connection | None = None
        self._lock = asyncio.Lock()
        self._waiters: dict[str, set[asyncio.Event]] = defaultdict(set)

    @contextlib.asynccontextmanager
    async def subscribe(self, key: str = ANY) -> AsyncIterator[asyncio.Event]:
        """Yield an event that is set whenever a notification with payload `key` arrives."""
        await self._ensure_listening()
        event = asyncio.Event()
        self._waiters[key].add(event)
        try:
            yield event
        finally:
            self._waiters[key].discard(event)
            if not self._waiters[key]:
                del self._waiters[key]

    async def close(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            await self._conn.close()
        self._conn = None

    async def _ensure_listening(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            return
        async with self._lock:
            if self._conn is not None and not self._conn.is_closed():
                return
            try:
                conn = await asyncpg.connect(get_settings().asyncpg_dsn)
                await conn.add_listener(self.channel, self._on_notify)
            except (OSError, asyncpg.PostgresError):
                # Waiters fall back to polling; the next subscribe retries.
                logger.warning("Could not LISTEN on %s", self.channel, exc_info=True)
                return
            self._conn = conn

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        for key in (payload, ANY):
            for event in self._waiters.get(key, ()):
                event.set()


async def wait(event: asyncio.Event, timeout: float) -> bool:
    """Wait for `event` up to `timeout` seconds, then clear it. Returns whether it fired."""
    try:
        await asyncio.wait_for(event.wait(), timeout)
    except TimeoutError:
        return False
    event.clear()
    return True
