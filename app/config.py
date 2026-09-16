"""Application configuration."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment: development, staging, production
    env: str = "development"

    # Database — PostgreSQL (default), SQLite for tests
    # Set PMO_DATABASE_URL=sqlite:///./pmo_system.db for local dev without Docker
    database_url: str = "postgresql://pmo:pmo_pass@localhost:5432/pmo_system"

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
    resend_api_key: str = ""  # Resend.com API key (preferred over SMTP)
    app_url: str = "http://localhost:8000"  # Base URL for reset links etc.

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

    @property
    def has_default_secret(self) -> bool:
        return self.secret_key == "dev-secret-key-change-in-production"

    model_config = {"env_file": ".env", "env_prefix": "PMO_", "extra": "ignore"}


settings = Settings()
