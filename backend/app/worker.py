"""Background worker: claims queued runs from Postgres and executes them.

Usage: `uv run python -m app.worker`

Several workers can run side by side; `FOR UPDATE SKIP LOCKED` hands each run to one.
"""

import asyncio
import logging
import signal
import uuid

from app.config import get_settings
from app.db import SessionLocal
from app.pubsub import RUN_QUEUED, Notifier, wait
from app.repositories import run as run_repo
from app.repositories import run_event as run_event_repo
from app.services.runtime.executor import Outcome, RunExecutor, ToolboxFactory, finish_run
from app.services.runtime.llm import LLM, AnthropicLLM
from app.services.runtime.tools import ServerToolbox

logger = logging.getLogger("app.worker")

# Look for queued runs at least this often, in case a notification was missed.
_POLL_SECONDS = 5.0
_REAP_EVERY_SECONDS = 30.0


class Worker:
    def __init__(self, *, llm: LLM, toolbox_factory: ToolboxFactory, concurrency: int):
        self._llm = llm
        self._toolbox_factory = toolbox_factory
        self._concurrency = concurrency
        self._active: dict[uuid.UUID, asyncio.Task[None]] = {}

    async def run(self, stop: asyncio.Event) -> None:
        notifier = Notifier(RUN_QUEUED)
        reaper = asyncio.create_task(self._reap_forever())
        try:
            async with notifier.subscribe() as queued:
                while not stop.is_set():
                    await self.claim_available()
                    await self._wait_for_work(queued, stop)
        finally:
            reaper.cancel()
            await self._shutdown()
            await notifier.close()

    async def claim_available(self) -> list[uuid.UUID]:
        """Start queued runs until the concurrency limit is reached."""
        started = []
        while len(self._active) < self._concurrency:
            async with SessionLocal() as db:
                run_id = await run_repo.claim_next(db)
                await db.commit()
            if run_id is None:
                break
            task = asyncio.create_task(self._execute(run_id))
            self._active[run_id] = task
            task.add_done_callback(lambda _, run_id=run_id: self._active.pop(run_id, None))
            started.append(run_id)
        return started

    async def wait_idle(self) -> None:
        """Wait until every started run has finished (used by tests)."""
        while self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)

    async def _execute(self, run_id: uuid.UUID) -> None:
        logger.info("Run %s started", run_id)
        executor = RunExecutor(run_id, llm=self._llm, toolbox_factory=self._toolbox_factory)
        try:
            await executor.execute()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Run %s crashed", run_id)
        logger.info("Run %s finished", run_id)

    async def _wait_for_work(self, queued: asyncio.Event, stop: asyncio.Event) -> None:
        waiters = [
            asyncio.create_task(stop.wait()),
            asyncio.create_task(wait(queued, _POLL_SECONDS)),
        ]
        if self._active and len(self._active) >= self._concurrency:
            # At capacity: also wake up when a slot frees.
            waiters.append(
                asyncio.create_task(
                    asyncio.wait(list(self._active.values()), return_when=asyncio.FIRST_COMPLETED)
                )
            )
        _, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()

    async def _reap_forever(self) -> None:
        while True:
            try:
                await reap_stale_runs()
            except Exception:
                logger.exception("Reaping stale runs failed")
            await asyncio.sleep(_REAP_EVERY_SECONDS)

    async def _shutdown(self) -> None:
        if not self._active:
            return
        logger.info("Stopping %d active run(s)", len(self._active))
        for task in self._active.values():
            task.cancel()
        await asyncio.gather(*self._active.values(), return_exceptions=True)


async def reap_stale_runs() -> list[uuid.UUID]:
    """Fail running runs whose worker stopped sending heartbeats (crashed or was killed)."""
    async with SessionLocal() as db:
        stale = await run_repo.find_stale(db, get_settings().run_stale_after_seconds)
    for run_id in stale:
        async with SessionLocal() as db:
            await finish_run(
                db,
                run_id,
                Outcome("failed", "The worker running this run stopped responding"),
                seq=await run_event_repo.next_seq(db, run_id),
            )
            await db.commit()
        logger.warning("Run %s marked failed: stale heartbeat", run_id)
    return stale


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    worker = Worker(
        llm=AnthropicLLM(),
        toolbox_factory=lambda agent, _conversation: ServerToolbox(agent),
        concurrency=get_settings().worker_concurrency,
    )
    logger.info("Worker started (concurrency %d)", get_settings().worker_concurrency)
    await worker.run(stop)
    logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
