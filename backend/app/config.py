from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_MANAGER_", env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+asyncpg://agent_manager:agent_manager@localhost:5433/agent_manager"
    )
    test_database_url: str = (
        "postgresql+asyncpg://agent_manager:agent_manager@localhost:5433/agent_manager_test"
    )
    jwt_secret: str = "dev-only-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    cors_origins: str = "http://localhost:3000"
    # Disables connection pooling; used by the test suite
    testing: bool = False
    # Claude API key for the worker. Unprefixed, as in the Anthropic SDKs; when unset the SDK
    # falls back to its other credential sources.
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    # Runs executed in parallel by one worker process
    worker_concurrency: int = 4
    # A running run whose heartbeat is older than this is marked failed
    run_stale_after_seconds: int = 60
    # Sandbox containers for the bash and file editor tools (see docker/sandbox)
    sandbox_image: str = "agent-manager-sandbox:latest"
    # Container runtime, e.g. "runsc" for gVisor; None uses Docker's default (runc)
    sandbox_runtime: str | None = None
    sandbox_memory: str = "1g"
    sandbox_cpus: float = 1.0
    sandbox_pids_limit: int = 256
    # Idle sandboxes are stopped (not removed) after this many minutes
    sandbox_idle_minutes: int = 30
    # Wall-clock limit for one bash command
    sandbox_command_timeout_seconds: int = 120

    @property
    def asyncpg_dsn(self) -> str:
        """`database_url` without the SQLAlchemy driver suffix, for raw asyncpg connections."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
