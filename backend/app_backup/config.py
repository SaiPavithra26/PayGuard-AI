"""Configuration settings for PayLater Shield."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root directory: payshield(paypal)/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_FILE = DEFAULT_DATA_DIR / "payshield.db"


class Settings(BaseSettings):
    """Application settings and environment configuration."""

    PROJECT_NAME: str = "PayGuard AI - PayLater Shield"
    VERSION: str = "0.1.0"
    API_PREFIX: str = "/api"

    # SQLite Database URL
    DATABASE_URL: str = f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"

    # Engine tuning
    DB_ECHO: bool = False

    # Allowed CORS Origins
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

