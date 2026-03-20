from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""                          # for text-embedding-3-small
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "gpu_errors"

    postgres_dsn: str = "postgresql+asyncpg://mas:changeme@localhost:5432/masdb"
    redis_url: str = "redis://localhost:6379/0"

    cache_ttl_active: int = 3600       # 1h — recent error fixes
    cache_ttl_static: int = 86400      # 24h — general GPU/Linux knowledge
    cache_cosine_threshold: float = 0.92

    log_level: str = "INFO"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
