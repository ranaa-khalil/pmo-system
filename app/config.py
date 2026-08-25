"""Application configuration."""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "sqlite:///./pmo_system.db"

    # Auth
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours

    # App
    app_name: str = "PMO System"
    debug: bool = True

    # GitHub integration (optional — set PMO_GITHUB_TOKEN to enable sync)
    github_token: str = ""

    # AI/LLM integration (optional — set to enable AI assistant)
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4o-mini"

    model_config = {"env_file": ".env", "env_prefix": "PMO_"}


settings = Settings()
