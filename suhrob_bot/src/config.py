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

    # Public channel users must join before using the bot.
    REQUIRE_CHANNEL_SUBSCRIPTION: bool = True
    REQUIRED_CHANNEL_ID: str = "@samarqand_uylari1"
    REQUIRED_CHANNEL_URL: str = "https://t.me/samarqand_uylari1"

    MEDIA_PATH: str = "/var/suhrob_bot/media"
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Asia/Tashkent"

    # Payment settings
    MONTHLY_PRICE_USD: int = 49
    CURRENCY_RATE_UZS_PER_USD: int = 12600
    PAYMENT_CLICK_CARD: str = "QR CODNI SKANERLANG"
    PAYMENT_CLICK_HOLDER: str = "BAHTIYOROV DONJIK"
    PAYMENT_CLICK_QR_FILE_ID: str = r"C:\suhrob\suhrob_bot\media\click.jpg"
    PAYMENT_HUMO_CARD: str = "9869100126034816"
    PAYMENT_HUMO_HOLDER: str = "BAHTIYOROV DONJIK"
    PAYMENT_HUMO_QR_FILE_ID: str = ""
    PAYMENT_UZCARD_CARD: str = "9869100126034816"
    PAYMENT_UZCARD_HOLDER: str = "BAHTIYOROV DONJIK"
    PAYMENT_UZCARD_QR_FILE_ID: str = ""
    PAYMENT_CARD_QR_FILE_ID: str = ""
    PAYMENT_CRYPTO_ADDRESS: str = "TUr3m7sAWpiysQs5S1jQkbxcvJARqAD8Rs"
    PAYMENT_CRYPTO_NETWORK: str = "USDT TRC-20"

    # Premium emoji IDs (optional, used when USE_PREMIUM_EMOJI=true)
    PREMIUM_EMOJI_HOUSE: str = ""
    PREMIUM_EMOJI_MONEY: str = ""
    PREMIUM_EMOJI_LOCATION: str = ""
    PREMIUM_EMOJI_FIRE: str = ""
    PREMIUM_EMOJI_STAR: str = ""

    # Instagram webhook (Salebot; ManyChat — legacy, убирается после переезда)
    PUBLIC_BASE_URL: str = ""
    INSTAGRAM_COMPANY_ID: Optional[int] = None
    SALEBOT_API_KEY: str = ""
    MANYCHAT_API_TOKEN: str = ""
    # client_type Salebot для Instagram. Нужен, чтобы при подключении к тому
    # же проекту WhatsApp/Telegram их сообщения не ушли в Instagram-ветку.
    # 0 = не проверять (принимаем любой канал).
    SALEBOT_INSTAGRAM_CLIENT_TYPE: int = 6

    # SendPulse API (OAuth client_credentials) — проактивная отправка
    # сообщений/фото контактам Instagram в обход синхронного /webhook/smmbot.
    # Значения задаются в Railway Variables, в репозитории не хранятся.
    SENDPULSE_API_ID: str = ""
    SENDPULSE_API_SECRET: str = ""
    SENDPULSE_BOT_ID: str = ""

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        return v


settings = Settings()
