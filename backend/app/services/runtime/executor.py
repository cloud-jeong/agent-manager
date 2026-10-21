"""Executes one run: the agent loop plus its bookkeeping (events, usage, cancellation).

The transcript is append-only. Assistant content is stored exactly as returned and replayed
unchanged, because thinking blocks are bound to the conversation they were produced in.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import DecryptionError
from app.db import SessionLocal
from app.models import Agent, Conversation
from app.repositories import conversation as conversation_repo
from app.repositories import mcp_server as mcp_server_repo
from app.repositories import run as run_repo
from app.repositories import run_event as run_event_repo
from app.services.runtime.events import EventWriter
from app.services.runtime.llm import LLM, TurnRequest
from app.services.runtime.tools import Toolbox, mcp_request

logger = logging.getLogger(__name__)

ToolboxFactory = Callable[[Agent, Conversation], Toolbox]

HEARTBEAT_SECONDS = 2.0


@dataclass
class Outcome:
    status: str
    error: str | None = None


class RunExecutor:
    def __init__(self, run_id: uuid.UUID, *, llm: LLM, toolbox_factory: ToolboxFactory):
        self.run_id = run_id
        self._llm = llm
        self._toolbox_factory = toolbox_factory
        self._events = EventWriter(run_id)
        self._cancelled_by_user = False

    async def execute(self) -> None:
        """Run to completion. The run must already be `running` (claimed by a worker)."""
        loop_task = asyncio.create_task(self._run_loop())
        watcher = asyncio.create_task(self._watch(loop_task))
        try:
            outcome = await loop_task
        except asyncio.CancelledError:
            if not self._cancelled_by_user:
                # The worker itself is shutting down.
                await self._finish(Outcome("failed", "The worker stopped while running"))
                raise
            outcome = Outcome("cancelled")
        except Exception as exc:
            logger.exception("Run %s failed", self.run_id)
            outcome = Outcome("failed", _describe_error(exc))
        finally:
            watcher.cancel()
        await self._finish(outcome)

    # -------------------------------------------------------------------------
    # The agent loop
    # -------------------------------------------------------------------------

    async def _run_loop(self) -> Outcome:
        async with SessionLocal() as db:
            run = await run_repo.get(db, self.run_id)
            assert run is not None
            agent = await db.get(Agent, run.agent_id)
            conversation = await db.get(Conversation, run.conversation_id)
            if agent is None or conversation is None:
                return Outcome("failed", "The agent or conversation no longer exists")
            if agent.deleted_at is not None or agent.agent_type != "agent":
                return Outcome("failed", "This agent can no longer be run")
            history = [
                {"role": m.role, "content": m.content}
                for m in await conversation_repo.list_messages(db, conversation.id)
            ]
            servers = (await mcp_server_repo.get_for_agents(db, [agent.id]))[agent.id]

        try:
            mcp = mcp_request(servers)
        except DecryptionError:
            return Outcome(
                "failed", "An MCP server token could not be decrypted; an admin must re-enter it"
            )
        toolbox = self._toolbox_factory(agent, conversation)
        tools = toolbox.definitions() + mcp.toolsets
        await self._events.emit("run_started", {"model": agent.model})

        for _ in range(agent.max_turns):
            result = await self._llm.run_turn(
                TurnRequest(
                    model=agent.model,
                    effort=agent.effort,
                    system=agent.system_prompt,
                    messages=history,
                    tools=tools,
                    mcp_servers=mcp.servers,
                    betas=mcp.betas,
                ),
                on_delta=self._events.delta,
                on_reset=self._reset_turn,
            )
            await self._events.flush()
            await self._record_usage(result.model, result)

            if result.stop_reason == "refusal":
                await self._reset_turn()
                return Outcome("failed", _refusal_message(result.stop_details))

            tool_uses = [b for b in result.content if b.get("type") == "tool_use"]
            if result.stop_reason == "max_tokens" and tool_uses:
                # A truncated tool input is not safe to run; drop the partial turn.
                await self._reset_turn()
                return Outcome("failed", "The model ran out of output tokens while calling a tool")

            if result.content:
                await self._append(history, "assistant", result.content)
            if result.stop_reason == "pause_turn":
                # A server tool hit its iteration limit; resend so it can continue.
                continue
            if not tool_uses:
                return Outcome("succeeded")

            results = []
            for block in tool_uses:
                await self._events.emit(
                    "tool_call", {"id": block["id"], "name": block["name"], "input": block["input"]}
                )
                output = await toolbox.execute(block["name"], block["input"])
                await self._events.emit(
                    "tool_result",
                    {"id": block["id"], "output": output.content, "isError": output.is_error},
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": output.content,
                        "is_error": output.is_error,
                    }
                )
            # All results of one turn go back in a single user message.
            await self._append(history, "user", results)

        return Outcome("failed", f"Stopped after {agent.max_turns} turns (the agent's limit)")

    async def _append(
        self, history: list[dict[str, Any]], role: str, content: list[dict[str, Any]]
    ) -> None:
        async with SessionLocal() as db:
            run = await run_repo.get(db, self.run_id)
            assert run is not None
            message = await conversation_repo.append_message(
                db, conversation_id=run.conversation_id, role=role, content=content, run_id=run.id
            )
            await run_event_repo.append(
                db,
                self.run_id,
                [self._events.take_event("message", {"messageId": str(message.id)})],
            )
            await db.commit()
        history.append({"role": role, "content": content})

    async def _record_usage(self, model: str, result: Any) -> None:
        async with SessionLocal() as db:
            await run_repo.add_usage(
                db,
                self.run_id,
                model=model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_read_input_tokens=result.cache_read_input_tokens,
            )
            run = await run_repo.get(db, self.run_id)
            assert run is not None
            await run_event_repo.append(
                db,
                self.run_id,
                [
                    self._events.take_event(
                        "usage",
                        {
                            "model": model,
                            "inputTokens": run.input_tokens,
                            "outputTokens": run.output_tokens,
                            "cacheReadInputTokens": run.cache_read_input_tokens,
                        },
                    )
                ],
            )
            await db.commit()

    async def _reset_turn(self) -> None:
        await self._events.emit("turn_reset", {})

    # -------------------------------------------------------------------------
    # Heartbeat, cancellation and completion
    # -------------------------------------------------------------------------

    async def _watch(self, loop_task: asyncio.Task[Outcome]) -> None:
        while not loop_task.done():
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                async with SessionLocal() as db:
                    cancel_requested = await run_repo.heartbeat(db, self.run_id)
                    await db.commit()
            except Exception:
                logger.warning("Heartbeat failed for run %s", self.run_id, exc_info=True)
                continue
            if cancel_requested:
                self._cancelled_by_user = True
                loop_task.cancel()
                return

    async def _finish(self, outcome: Outcome) -> None:
        try:
            await self._events.flush()
        except Exception:
            logger.warning("Could not flush events for run %s", self.run_id, exc_info=True)
        async with SessionLocal() as db:
            await finish_run(
                db, self.run_id, outcome, seq=await run_event_repo.next_seq(db, self.run_id)
            )
            await db.commit()


async def finish_run(db: AsyncSession, run_id: uuid.UUID, outcome: Outcome, *, seq: int) -> None:
    """Mark the run finished and make the transcript valid for the next request.

    Used by the executor and by the reaper for runs whose worker died. The caller commits.
    """
    if not await run_repo.finish(db, run_id, status=outcome.status, error=outcome.error):
        return
    run = await run_repo.get(db, run_id)
    assert run is not None
    # Every tool_use needs a matching tool_result before the conversation can continue.
    last = await conversation_repo.get_last_message(db, run.conversation_id)
    if last is not None and last.role == "assistant":
        dangling = [b for b in last.content if b.get("type") == "tool_use"]
        if dangling:
            reason = "Cancelled by the user" if outcome.status == "cancelled" else outcome.error
            await conversation_repo.append_message(
                db,
                conversation_id=run.conversation_id,
                role="user",
                run_id=run.id,
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": b["id"],
                        "content": f"Not executed: {reason}",
                        "is_error": True,
                    }
                    for b in dangling
                ],
            )
    await conversation_repo.touch(db, run.conversation_id)
    await run_event_repo.append(
        db,
        run_id,
        [(seq, "run_finished", {"status": outcome.status, "error": outcome.error})],
    )


def _refusal_message(stop_details: dict[str, Any] | None) -> str:
    category = (stop_details or {}).get("category")
    suffix = f" (category: {category})" if category else ""
    return f"The model declined this request{suffix}"


def _describe_error(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
    return message[:2000]
