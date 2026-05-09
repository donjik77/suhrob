from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_NAME: str = "Suhrob HOUSE Bot Platform"
    USE_PREMIUM_EMOJI: bool = False

    DATABASE_URL: str
    REDIS_URL: str = "redis://redis:6379/0"

    # Developer is the only hardcoded role — never blocked
    DEVELOPER_TELEGRAM_ID: int
    DEVELOPER_NAME: str = "Developer"

    # Pre-configured director and agents (auto-registered on startup)
    DIRECTOR_TELEGRAM_ID: Optional[int] = None
    AGENT_1_TELEGRAM_ID: Optional[int] = None
    AGENT_2_TELEGRAM_ID: Optional[int] = None
    AGENT_3_TELEGRAM_ID: Optional[int] = None

    # OpenRouter AI
    OPENROUTER_API_KEY: str = "REPLACE_WITH_YOUR_API_KEY"
    OPENROUTER_MODEL: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    AI_DAILY_LIMIT_PER_USER: int = 50

    MEDIA_PATH: str = "/var/suhrob_bot/media"
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Asia/Tashkent"

    # Payment settings
    MONTHLY_PRICE_USD: int = 49
    CURRENCY_RATE_UZS_PER_USD: int = 12600
    PAYMENT_CLICK_CARD: str = ""
    PAYMENT_CLICK_HOLDER: str = ""
    PAYMENT_CLICK_QR_FILE_ID: str = ""
    PAYMENT_HUMO_CARD: str = ""
    PAYMENT_HUMO_HOLDER: str = ""
    PAYMENT_HUMO_QR_FILE_ID: str = ""
    PAYMENT_UZCARD_CARD: str = ""
    PAYMENT_UZCARD_HOLDER: str = ""
    PAYMENT_UZCARD_QR_FILE_ID: str = ""
    PAYMENT_CARD_QR_FILE_ID: str = ""
    PAYMENT_CRYPTO_ADDRESS: str = ""
    PAYMENT_CRYPTO_NETWORK: str = "USDT TRC-20"

    # Premium emoji IDs (optional, used when USE_PREMIUM_EMOJI=true)
    PREMIUM_EMOJI_HOUSE: str = ""
    PREMIUM_EMOJI_MONEY: str = ""
    PREMIUM_EMOJI_LOCATION: str = ""
    PREMIUM_EMOJI_FIRE: str = ""
    PREMIUM_EMOJI_STAR: str = ""

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v


settings = Settings()
