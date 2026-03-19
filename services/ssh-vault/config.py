from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    vault_master_key: str
    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    internal_api_key: str
    log_level: str = "INFO"
    session_ttl_seconds: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
