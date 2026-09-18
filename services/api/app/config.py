"""Environment-based service settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    title: str = "CoachLens API"
    service_name: str = "coachlens-api"
    diagnostic_evaluations_path: Path | None = None
    bedrock_enabled: bool = Field(default=False, validation_alias="COACHLENS_BEDROCK_ENABLED")
    bedrock_region: str = Field(default="us-east-1", validation_alias="COACHLENS_BEDROCK_REGION")
    bedrock_model_id: str = Field(default="global.anthropic.claude-sonnet-4-6",
                                  validation_alias="COACHLENS_BEDROCK_MODEL_ID")

    model_config = SettingsConfigDict(
        env_prefix="COACHLENS_API_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
