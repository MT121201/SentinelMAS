from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    redis_url: str = "redis://localhost:6379/0"

    orchestrator_url: str = "http://orchestrator:8001"
    internal_api_key: str = ""

    # Delivery
    manager_webhook_url: str = ""          # Slack / Teams / custom webhook
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "sentinelmas@company.com"
    smtp_to: str = ""                       # comma-separated recipients

    # Langfuse cost data (Phase 8 — degrades gracefully if not set)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://langfuse:3000"

    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
