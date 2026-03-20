from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    # Sync DSN for APScheduler job store (APScheduler 3.x uses sync SQLAlchemy)
    postgres_dsn_sync: str = "postgresql://mas:changeme@localhost:5432/masdb"

    redis_url: str = "redis://localhost:6379/0"

    internal_api_key: str = ""

    # Queue names (without the mas: prefix and _queue suffix)
    queue_orchestrator: str = "orchestrator"
    queue_client: str = "client"
    queue_inserver: str = "inserver"
    queue_report: str = "report"

    # Worker pool
    max_concurrent_tasks: int = 10
    stuck_task_threshold_seconds: int = 900   # 15 minutes

    # Langfuse (Phase 8 — degrades gracefully if not set)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3000"

    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
