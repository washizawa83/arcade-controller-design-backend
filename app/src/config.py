"""Application configuration settings."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application settings
    app_name: str = Field(
        default="Arcade Controller Design Backend", description="Application name"
    )
    app_version: str = Field(default="0.1.0", description="Application version")
    debug: bool = Field(default=True, description="Debug mode")

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")

    # CORS settings
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins",
    )

    # Database settings (for future use)
    database_url: str = Field(
        default="sqlite:///./arcade_controller.db", description="Database URL"
    )

    # Security settings
    secret_key: str = Field(
        default="your-secret-key-change-this-in-production",
        description="Secret key for JWT tokens",
    )
    algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(
        default=30, description="Access token expiration time in minutes"
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()
