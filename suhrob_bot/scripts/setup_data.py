"""
One-time setup: populates payment settings, channel ID, and company.
Run AFTER alembic upgrade head and scripts/init.py:
    cd suhrob_bot
    python scripts/setup_data.py
"""
import asyncio
import sys

sys.path.insert(0, ".")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import settings
from src.db.models import Company
from src.db.repositories.settings_repo import SettingsRepository
from sqlalchemy import select


PAYMENT_SETTINGS = {
    "payment_click_card": "9869100126034816",
    "payment_click_holder": "Suhrob HOUSE",
    "payment_humo_card": "9869100126034816",
    "payment_humo_holder": "Suhrob HOUSE",
    "payment_uzcard_card": "9869100126034816",
    "payment_uzcard_holder": "Suhrob HOUSE",
    "payment_crypto_address": "TUr3m7sAWpiysQs5S1jQkbxcvJARqAD8Rs",
    "payment_crypto_network": "USDT TRC-20",
    "monthly_price_usd": "49",
    "currency_rate_uzs_per_usd": "12600",
}

CHANNEL_ID = "@samuylariix"


async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    SessionFactory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionFactory() as session:
        # Update payment settings
        repo = SettingsRepository(session)
        for key, value in PAYMENT_SETTINGS.items():
            await repo.set(key, value)
            print(f"✅ {key} = {value}")

        # Update company channel
        result = await session.execute(select(Company).limit(1))
        company = result.scalar_one_or_none()
        if company:
            company.telegram_channel_id = CHANNEL_ID
            await session.commit()
            print(f"✅ Kompaniya '{company.name}' kanalga ulandi: {CHANNEL_ID}")
        else:
            print("⚠️  Kompaniya topilmadi. Avval scripts/init.py ni ishga tushiring.")

    await engine.dispose()
    print("\n🎉 Setup muvaffaqiyatli yakunlandi!")


if __name__ == "__main__":
    asyncio.run(main())
