from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, auth, members, teams, users
from app.config import get_settings
from app.errors import register_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Agent Manager API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for module in (auth, users, teams, agents, members):
        app.include_router(module.router)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
