import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from src.db.models import BotSetting

DEFAULT_SETTINGS = {
    "monthly_price_usd": "49",
    "currency_rate_uzs_per_usd": "12600",
    "payment_click_card": "",
    "payment_click_holder": "",
    "payment_click_qr_file_id": "",
    "payment_humo_card": "",
    "payment_humo_holder": "",
    "payment_humo_qr_file_id": "",
    "payment_uzcard_card": "",
    "payment_uzcard_holder": "",
    "payment_uzcard_qr_file_id": "",
    "payment_card_qr_file_id": "",
    "payment_crypto_address": "",
    "payment_crypto_network": "USDT TRC-20",
}

_DOTENV_CACHE: dict[str, str] | None = None


def _load_dotenv_values() -> dict[str, str]:
    global _DOTENV_CACHE
    if _DOTENV_CACHE is not None:
        return _DOTENV_CACHE

    env_path = Path(__file__).resolve().parents[3] / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value

    _DOTENV_CACHE = values
    return values


def _env_candidates(key: str) -> list[str]:
    upper = key.upper()
    candidates = [upper, key]

    if upper.startswith("PAYMENT_"):
        candidates.append(upper.removeprefix("PAYMENT_"))

    if upper.endswith("_FILE_ID"):
        candidates.append(upper.removesuffix("_FILE_ID"))
        if upper.startswith("PAYMENT_"):
            candidates.append(upper.removeprefix("PAYMENT_").removesuffix("_FILE_ID"))

    if upper.endswith("_PHOTO"):
        candidates.append(upper.removesuffix("_PHOTO"))
        if upper.startswith("PAYMENT_"):
            candidates.append(upper.removeprefix("PAYMENT_").removesuffix("_PHOTO"))

    return list(dict.fromkeys(candidates))


def _get_env_fallback(key: str) -> Optional[str]:
    candidates = _env_candidates(key)
    for candidate in candidates:
        value = os.environ.get(candidate)
        if value:
            return value

    dotenv_values = _load_dotenv_values()
    for candidate in candidates:
        value = dotenv_values.get(candidate)
        if value:
            return value
    return None


def _prefers_env(key: str) -> bool:
    upper = key.upper()
    return upper.startswith("PAYMENT_") or upper in {
        "MONTHLY_PRICE_USD",
        "CURRENCY_RATE_UZS_PER_USD",
    }


class SettingsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if _prefers_env(key):
            env_value = _get_env_fallback(key)
            if env_value:
                return env_value

        result = await self.session.execute(
            select(BotSetting.value).where(BotSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row and row.strip():
            return row
        return _get_env_fallback(key) or default

    async def get_int(self, key: str, default: int = 0) -> int:
        val = await self.get(key)
        try:
            return int(val) if val else default
        except (ValueError, TypeError):
            return default

    async def get_float(self, key: str, default: float = 0.0) -> float:
        val = await self.get(key)
        try:
            return float(val) if val else default
        except (ValueError, TypeError):
            return default

    async def get_decimal(self, key: str, default: Decimal = Decimal("0")) -> Decimal:
        val = await self.get(key)
        try:
            return Decimal(val) if val else default
        except (InvalidOperation, TypeError):
            return default

    async def set(self, key: str, value: str, updated_by: Optional[int] = None) -> None:
        stmt = insert(BotSetting).values(key=key, value=value, updated_by=updated_by)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": value, "updated_by": updated_by},
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_all(self) -> dict[str, str]:
        result = await self.session.execute(select(BotSetting))
        return {row.key: row.value for row in result.scalars().all()}

    async def init_defaults(self) -> None:
        for key, value in DEFAULT_SETTINGS.items():
            existing = await self.get(key)
            if existing is None:
                await self.set(key, value)
