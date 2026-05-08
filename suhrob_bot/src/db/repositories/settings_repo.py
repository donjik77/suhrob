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
    "payment_humo_card": "",
    "payment_humo_holder": "",
    "payment_uzcard_card": "",
    "payment_uzcard_holder": "",
    "payment_crypto_address": "",
    "payment_crypto_network": "USDT TRC-20",
}


class SettingsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        result = await self.session.execute(
            select(BotSetting.value).where(BotSetting.key == key)
        )
        row = result.scalar_one_or_none()
        return row if row is not None else default

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
