from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User, UserRole, Company
from src.bot.keyboards.client import main_menu_kb, property_card_kb
from src.bot.keyboards.agent import agent_menu_kb
from src.bot.handlers.client.property_access import get_active_property_for_client
from src.bot.utils.property_media import answer_property_media_card
from src.utils.formatters import format_property_card
from locales.uz import t

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User, command: CommandObject, db_session: AsyncSession, company: Company, state: FSMContext):
    name = message.from_user.full_name or message.from_user.username or "Foydalanuvchi"

    # Handle deep-link: /start property_123
    arg = command.args or ""
    if arg.startswith("property_") and db_user.role == UserRole.client:
        try:
            property_id = int(arg.split("_", 1)[1])
            await _show_property_deeplink(message, db_session, property_id, db_user, company, state)
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


async def _show_property_deeplink(
    message: Message,
    session: AsyncSession,
    property_id: int,
    db_user: User,
    company: Company | None,
    state: FSMContext | None = None,
) -> None:
    from src.db.repositories.settings_repo import SettingsRepository

    prop = await get_active_property_for_client(property_id, company, session, with_media=True, with_agent=True)

    if not prop:
        await message.answer(t("welcome", name=message.from_user.full_name or "Foydalanuvchi"), reply_markup=main_menu_kb(), parse_mode="HTML")
        return

    from sqlalchemy import update
    from src.db.models import Property
    await session.execute(
        update(Property)
        .where(Property.id == prop.id, Property.company_id == prop.company_id)
        .values(views_count=Property.views_count + 1)
    )
    await session.commit()

    settings_repo = SettingsRepository(session)
    rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
    caption = format_property_card(prop, rate)

    await answer_property_media_card(
        message,
        media_items=prop.media,
        caption=caption,
        reply_markup=property_card_kb(property_id),
        parse_mode="HTML",
        caption_entities_json=prop.custom_text_entities_json if prop.custom_text else None,
    )

    if state:
        from src.bot.handlers.client.ai_consultation import ConsultState
        await state.set_state(ConsultState.chatting)
        await state.update_data(property_id=property_id)
        await message.answer(
            "💬 Shu uy haqida savollaringizni yozing, men yordam beraman.\n\n❌ Chiqish uchun /stop yozing.",
        )

    await message.answer(t("welcome", name=message.from_user.full_name or "Foydalanuvchi"), reply_markup=main_menu_kb(), parse_mode="HTML")
