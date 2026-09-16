"""Environment-based service settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    title: str = "CoachLens API"
    service_name: str = "coachlens-api"

    model_config = SettingsConfigDict(
        env_prefix="COACHLENS_API_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
