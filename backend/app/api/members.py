from fastapi import APIRouter

from app.api.deps import CurrentActor, DbSession
from app.repositories import user as user_repo
from app.schemas.user import DefaultAgentRead, DefaultAgentUpdate
from app.services import agent as agent_service

router = APIRouter(prefix="/api/members", tags=["members"])


@router.get("/default-agent", response_model=DefaultAgentRead, operation_id="getDefaultAgent")
async def get_default_agent(actor: CurrentActor, db: DbSession) -> DefaultAgentRead:
    return DefaultAgentRead(default_agent_id=await user_repo.get_default_agent_id(db, actor.id))


@router.put("/default-agent", response_model=DefaultAgentRead, operation_id="setDefaultAgent")
async def set_default_agent(
    body: DefaultAgentUpdate, actor: CurrentActor, db: DbSession
) -> DefaultAgentRead:
    if body.default_agent_id is not None:
        # The caller may only pin an active agent they can see.
        await agent_service.get_visible_active_agent(db, actor, body.default_agent_id)
    await user_repo.set_default_agent_id(db, actor.id, body.default_agent_id)
    await db.commit()
    return DefaultAgentRead(default_agent_id=body.default_agent_id)
