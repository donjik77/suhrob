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
from src.db.repositories.settings_repo import (
    DEFAULT_SETTINGS,
    SettingsRepository,
    _get_env_fallback,
)
from sqlalchemy import select


PAYMENT_SETTING_KEYS = (
    "payment_click_card",
    "payment_click_holder",
    "payment_click_qr_file_id",
    "payment_humo_card",
    "payment_humo_holder",
    "payment_humo_qr_file_id",
    "payment_uzcard_card",
    "payment_uzcard_holder",
    "payment_uzcard_qr_file_id",
    "payment_card_qr_file_id",
    "payment_crypto_address",
    "payment_crypto_network",
    "monthly_price_usd",
    "currency_rate_uzs_per_usd",
)

CHANNEL_ID = "@samarqand_uylari1"


async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    SessionFactory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionFactory() as session:
        # Update payment settings
        repo = SettingsRepository(session)
        for key in PAYMENT_SETTING_KEYS:
            value = _get_env_fallback(key) or DEFAULT_SETTINGS.get(key, "")
            if not value:
                print(f"⚠️  {key} env qiymati topilmadi, o'tkazib yuborildi")
                continue
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
