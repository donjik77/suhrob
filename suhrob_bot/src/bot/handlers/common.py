from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User, UserRole
from src.bot.keyboards.client import main_menu_kb, property_card_kb
from src.bot.keyboards.agent import agent_menu_kb
from src.utils.formatters import format_property_card
from locales.uz import t

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User, command: CommandObject, db_session: AsyncSession):
    name = message.from_user.full_name or message.from_user.username or "Foydalanuvchi"

    # Handle deep-link: /start property_123
    arg = command.args or ""
    if arg.startswith("property_") and db_user.role == UserRole.client:
        try:
            property_id = int(arg.split("_", 1)[1])
            await _show_property_deeplink(message, db_session, property_id, db_user)
            return
        except (ValueError, IndexError):
            pass

    if db_user.role == UserRole.client:
        await message.answer(
            t("welcome", name=name),
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            t("agent_menu_welcome", name=name),
            reply_markup=agent_menu_kb(db_user.role),
            parse_mode="HTML",
        )


async def _show_property_deeplink(message: Message, session: AsyncSession, property_id: int, db_user: User) -> None:
    from sqlalchemy import select
    from src.db.models import Property, PropertyStatus
    from src.db.repositories.settings_repo import SettingsRepository

    prop = (
        await session.execute(
            select(Property).where(Property.id == property_id, Property.status == PropertyStatus.active)
        )
    ).scalar_one_or_none()

    if not prop:
        await message.answer(t("welcome", name=message.from_user.full_name or "Foydalanuvchi"), reply_markup=main_menu_kb(), parse_mode="HTML")
        return

    settings_repo = SettingsRepository(session)
    rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
    caption = format_property_card(prop, rate)

    photos = [m for m in (prop.media or []) if m.file_type.value == "photo"]
    kb = property_card_kb(property_id)

    if photos:
        from aiogram.types import InputMediaPhoto
        if len(photos) > 1:
            media = [InputMediaPhoto(media=photos[0].file_id, caption=caption, parse_mode="HTML"),
                     *[InputMediaPhoto(media=p.file_id) for p in photos[1:]]]
            await message.answer_media_group(media)
            await message.answer("👆", reply_markup=kb)
        else:
            await message.answer_photo(photos[0].file_id, caption=caption, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(caption, parse_mode="HTML", reply_markup=kb)

    await message.answer(t("welcome", name=message.from_user.full_name or "Foydalanuvchi"), reply_markup=main_menu_kb(), parse_mode="HTML")
