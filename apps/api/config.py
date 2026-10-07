from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://patchpulse:patchpulse@localhost:5432/patchpulse"
    redis_url: str = "redis://localhost:6379/0"

    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dim: int = 768

    llm_model: str = ""
    classify_batch_size: int = 20

    @property
    def sync_database_url(self) -> str:
        """psycopg (sync) URL for Alembic and scripts."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    return Settings()
