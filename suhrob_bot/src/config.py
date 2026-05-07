from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str
    BOT_NAME: str = "Suhrob HOUSE"

    DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"

    DEVELOPER_TELEGRAM_ID: int

    MEDIA_PATH: str = "/var/suhrob_bot/media"

    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Asia/Tashkent"

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v


settings = Settings()
