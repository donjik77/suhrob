from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.db.models import User
from src.db.session import AsyncSessionFactory
from src.db.repositories.settings_repo import SettingsRepository
from src.db.repositories.property_repo import PropertyRepository
from src.bot.keyboards.client import favorites_kb, main_menu_kb
from src.utils.formatters import format_property_card
from locales.uz import t

router = Router()


@router.message(F.text == "⭐ Saralangan")
async def show_favorites(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import ClientFavorite, Property, PropertyStatus
        from sqlalchemy.orm import selectinload

        result = await session.execute(
            select(ClientFavorite)
            .where(ClientFavorite.user_id == db_user.id)
            .options(
                selectinload(ClientFavorite.property)
                .selectinload(Property.media),
                selectinload(ClientFavorite.property)
                .selectinload(Property.agent),
            )
            .order_by(ClientFavorite.created_at.desc())
        )
        favorites = list(result.scalars().all())

        if not favorites:
            await message.answer(t("favorites_empty"), reply_markup=main_menu_kb())
            return

        settings_repo = SettingsRepository(session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

        await message.answer(t("favorites_title", count=len(favorites)))

        for fav in favorites:
            prop = fav.property
            if not prop or prop.status.value == "hidden":
                continue
            card_text = format_property_card(prop, rate)
            kb = favorites_kb(prop.id)
            if prop.media:
                await message.answer_photo(photo=prop.media[0].file_id, caption=card_text, reply_markup=kb)
            else:
                await message.answer(card_text, reply_markup=kb)


@router.callback_query(F.data.startswith("prop_fav:"))
async def add_to_favorites(callback: CallbackQuery, db_user: User):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import ClientFavorite

        existing = await session.execute(
            select(ClientFavorite).where(
                ClientFavorite.user_id == db_user.id,
                ClientFavorite.property_id == property_id,
            )
        )
        if existing.scalar_one_or_none():
            await callback.answer(t("favorite_already"))
            return

        fav = ClientFavorite(user_id=db_user.id, property_id=property_id)
        session.add(fav)
        await session.commit()

    await callback.answer(t("favorite_saved"), show_alert=True)


@router.callback_query(F.data.startswith("prop_unfav:"))
async def remove_from_favorites(callback: CallbackQuery, db_user: User):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import delete
        from src.db.models import ClientFavorite

        await session.execute(
            delete(ClientFavorite).where(
                ClientFavorite.user_id == db_user.id,
                ClientFavorite.property_id == property_id,
            )
        )
        await session.commit()

    await callback.answer(t("favorite_removed"), show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data.startswith("prop_contact:"))
async def contact_agent(callback: CallbackQuery, db_user: User):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        prop_repo = PropertyRepository(session)
        prop = await prop_repo.get_by_id(property_id)

        if not prop or not prop.agent:
            await callback.answer("Agent topilmadi", show_alert=True)
            return

        agent = prop.agent
        username_str = f"@{agent.username}" if agent.username else "(username yo'q)"
        phone_str = agent.phone or "(telefon yo'q)"
        name_str = agent.full_name or agent.username or str(agent.telegram_user_id)

        await callback.message.answer(
            t("agent_contact", name=name_str, phone=phone_str, username=username_str)
        )

        # Notify the agent
        try:
            client_name = db_user.full_name or db_user.username or str(db_user.telegram_user_id)
            from aiogram import Bot
            # Bot instance is injected via middleware — we retrieve from the event
            bot = callback.bot
            await bot.send_message(
                chat_id=agent.telegram_user_id,
                text=t("agent_notify_new_client", client_name=client_name, property_title=prop.title),
            )
        except Exception:
            pass  # Non-critical — agent notification failure doesn't break client flow

    await callback.answer()
