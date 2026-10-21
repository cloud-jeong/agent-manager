from functools import lru_cache

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
    # Runs executed in parallel by one worker process
    worker_concurrency: int = 4
    # A running run whose heartbeat is older than this is marked failed
    run_stale_after_seconds: int = 60

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
