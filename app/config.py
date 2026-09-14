"""Application configuration."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment: development, staging, production
    env: str = "development"

    # Database — SQLite for dev, PostgreSQL for staging/prod
    # Set PMO_DATABASE_URL=postgresql://user:pass@host:5432/dbname for prod
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

    # Email (optional — set to enable email notifications)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@pmosystem.app"

    # Sentry (optional — set to enable error tracking)
    sentry_dsn: str = ""

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_staging(self) -> bool:
        return self.env == "staging"

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    model_config = {"env_file": ".env", "env_prefix": "PMO_"}


settings = Settings()
