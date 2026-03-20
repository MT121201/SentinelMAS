from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    redis_url: str = "redis://localhost:6379/0"

    vault_url: str = "http://ssh-vault:8100"
    internal_api_key: str = ""

    orchestrator_url: str = "http://orchestrator:8001"

    # Session TTL requested from vault (seconds)
    vault_session_ttl: int = 300

    # SSH command timeout (seconds)
    ssh_command_timeout: int = 30

    # Disk usage threshold to alert (%)
    disk_alert_threshold_pct: float = 85.0

    # GPU memory usage threshold to alert (%)
    gpu_memory_alert_threshold_pct: float = 90.0

    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
