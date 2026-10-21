"""Writes a run's progress to `run_events` for SSE subscribers.

Text and thinking deltas are coalesced so a long answer becomes a few dozen rows
instead of one row per token.
"""

import time
import uuid
from typing import Any

from app.db import SessionLocal
from app.repositories import run_event as run_event_repo
from app.services.runtime.llm import DeltaKind

FLUSH_INTERVAL_SECONDS = 0.1


class EventWriter:
    def __init__(self, run_id: uuid.UUID, start_seq: int = 0):
        self.run_id = run_id
        self._seq = start_seq
        self._pending_kind: DeltaKind | None = None
        self._pending_text: list[str] = []
        self._last_flush = time.monotonic()

    @property
    def next_seq(self) -> int:
        return self._seq

    async def delta(self, kind: DeltaKind, text: str) -> None:
        if self._pending_kind not in (None, kind):
            await self.flush()
        self._pending_kind = kind
        self._pending_text.append(text)
        if time.monotonic() - self._last_flush >= FLUSH_INTERVAL_SECONDS:
            await self.flush()

    async def emit(self, type_: str, data: dict[str, Any]) -> None:
        await self._write([self._take_pending(), self._event(type_, data)])

    async def flush(self) -> None:
        await self._write([self._take_pending()])

    def take_event(self, type_: str, data: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
        """Reserve a seq for an event the caller writes in its own transaction."""
        return self._event(type_, data)

    def _take_pending(self) -> tuple[int, str, dict[str, Any]] | None:
        if not self._pending_text or self._pending_kind is None:
            return None
        event = self._event(f"{self._pending_kind}_delta", {"text": "".join(self._pending_text)})
        self._pending_kind = None
        self._pending_text = []
        return event

    def _event(self, type_: str, data: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
        event = (self._seq, type_, data)
        self._seq += 1
        return event

    async def _write(self, events: list[tuple[int, str, dict[str, Any]] | None]) -> None:
        self._last_flush = time.monotonic()
        rows = [e for e in events if e is not None]
        if not rows:
            return
        async with SessionLocal() as db:
            await run_event_repo.append(db, self.run_id, rows)
            await db.commit()
