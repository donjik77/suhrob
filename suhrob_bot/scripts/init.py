"""
Initial setup script. Run after `alembic upgrade head`.
Creates developer user, company, director, and initial subscription.
"""
import asyncio
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.config import settings
from src.db.models import (
    Base, User, UserRole, Company, Subscription, SubscriptionStatus, BotSetting
)
from src.db.repositories.settings_repo import SettingsRepository, DEFAULT_SETTINGS


async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    SessionFactory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionFactory() as session:
        print("=== Suhrob HOUSE Bot — Dastlabki sozlash ===\n")

        dev_tg_id = settings.DEVELOPER_TELEGRAM_ID
        print(f"Dasturchi Telegram ID: {dev_tg_id}")

        # Create developer user
        from sqlalchemy import select
        existing_dev = await session.execute(
            select(User).where(User.telegram_user_id == dev_tg_id)
        )
        dev_user = existing_dev.scalar_one_or_none()
        if not dev_user:
            dev_user = User(
                telegram_user_id=dev_tg_id,
                full_name="Developer",
                role=UserRole.developer,
            )
            session.add(dev_user)
            await session.flush()
            print(f"✅ Dasturchi yaratildi (ID: {dev_user.id})")
        else:
            dev_user.role = UserRole.developer
            print(f"✅ Dasturchi mavjud (ID: {dev_user.id})")

        # Create company
        existing_company = await session.execute(select(Company).limit(1))
        company = existing_company.scalar_one_or_none()
        if not company:
            company_name = input("\nKompaniya nomi [Suhrob HOUSE]: ").strip() or "Suhrob HOUSE"
            channel_id = input("Telegram kanal ID (masalan: @suhrob_house_channel yoki -1001234567890): ").strip()
            company = Company(
                name=company_name,
                telegram_channel_id=channel_id or None,
                is_active=True,
            )
            session.add(company)
            await session.flush()
            print(f"✅ Kompaniya yaratildi: {company.name} (ID: {company.id})")
        else:
            print(f"✅ Kompaniya mavjud: {company.name} (ID: {company.id})")

        # Create director
        director_tg_id_str = input(f"\nDirektor (Suhrob aka) Telegram ID: ").strip()
        if director_tg_id_str:
            director_tg_id = int(director_tg_id_str)
            existing_dir = await session.execute(
                select(User).where(User.telegram_user_id == director_tg_id)
            )
            director = existing_dir.scalar_one_or_none()
            if not director:
                director = User(
                    telegram_user_id=director_tg_id,
                    full_name="Suhrob aka",
                    role=UserRole.director,
                    company_id=company.id,
                )
                session.add(director)
                print(f"✅ Direktor yaratildi (Telegram ID: {director_tg_id})")
            else:
                director.role = UserRole.director
                director.company_id = company.id
                print(f"✅ Direktor yangilandi (Telegram ID: {director_tg_id})")

        # Create initial active subscription (30-day trial)
        existing_sub = await session.execute(
            select(Subscription).where(
                Subscription.company_id == company.id,
                Subscription.status == SubscriptionStatus.active,
            )
        )
        if not existing_sub.scalar_one_or_none():
            now = datetime.utcnow()
            sub = Subscription(
                company_id=company.id,
                price_usd=0,
                period_start=now,
                period_end=now + timedelta(days=30),
                status=SubscriptionStatus.active,
            )
            session.add(sub)
            print(f"✅ 30 kunlik bepul sinov obuna yaratildi.")

        # Init default bot settings
        repo = SettingsRepository(session)
        await repo.init_defaults()
        print("✅ Standart sozlamalar saqlandi.")

        await session.commit()
        print("\n🎉 Sozlash muvaffaqiyatli yakunlandi!")
        print("Endi botni ishga tushiring: docker-compose up -d")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
