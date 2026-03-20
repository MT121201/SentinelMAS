from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    redis_url: str = "redis://localhost:6379/0"

    vault_url: str = "http://ssh-vault:8100"
    rag_url: str = "http://rag-service:8005"
    orchestrator_url: str = "http://orchestrator:8001"
    internal_api_key: str = ""

    tavily_api_key: str = ""
    serpapi_key: str = ""

    vault_session_ttl: int = 300
    ssh_command_timeout: int = 60      # tickets may need longer-running commands
    max_agent_turns: int = 30
    max_retry_attempts: int = 2        # retries before escalating

    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
