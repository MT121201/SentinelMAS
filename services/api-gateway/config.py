from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24
    internal_api_key: str

    # Admin credentials (env-based for MVP — upgrade to DB users in v2)
    admin_username: str = "admin"
    admin_password_hash: str  # bcrypt hash of admin password

    # Downstream services
    vault_url: str = "http://ssh-vault:8100"
    orchestrator_url: str = "http://orchestrator:8001"

    # Shared infra
    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    redis_url: str = "redis://localhost:6379/0"

    # App
    env: str = "development"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
