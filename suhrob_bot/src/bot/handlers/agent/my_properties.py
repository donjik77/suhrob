import math

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery

from src.db.models import User, UserRole, PropertyStatus
from src.db.session import AsyncSessionFactory
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.keyboards.agent import (
    my_properties_nav_kb, property_actions_kb, property_status_kb, delete_confirm_kb
)
from src.bot.filters.role import RoleFilter
from src.services.publisher_service import PublisherService
from src.utils.formatters import format_property_card, PROPERTY_TYPE_ICONS
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))

PAGE_SIZE = 5


@router.message(F.text == "📋 Mening uylarim")
async def my_properties(message: Message, db_user: User):
    await _show_properties_page(message, db_user, page=1, send=True)


@router.callback_query(F.data.startswith("my_props_page:"))
async def paginate_properties(callback: CallbackQuery, db_user: User):
    page = int(callback.data.split(":")[1])
    await _show_properties_page(callback.message, db_user, page=page, send=False, edit=True)
    await callback.answer()


async def _show_properties_page(event, db_user: User, page: int, send: bool, edit: bool = False):
    offset = (page - 1) * PAGE_SIZE

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        props, total = await repo.get_agent_properties(db_user.id, offset=offset, limit=PAGE_SIZE)

    if not props and page == 1:
        text = t("my_props_empty")
        if send:
            await event.answer(text)
        else:
            await event.edit_text(text)
        return

    total_pages = max(1, math.ceil(total / PAGE_SIZE))

    lines = [t("my_props_title", total=total), ""]
    for i, prop in enumerate(props, start=offset + 1):
        icon = PROPERTY_TYPE_ICONS.get(prop.property_type, "🏠")
        status_label = t(f"prop_status_{prop.status.value}")
        price = int(prop.price_usd)
        lines.append(
            f"{i}. {icon} {prop.location_district}, ${price:,}, {prop.rooms} xona — {status_label}"
        )

    text = "\n".join(lines)
    kb = my_properties_nav_kb(page, total_pages)

    # Add property selection buttons
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for prop in props:
        builder.button(
            text=f"#{prop.id} {prop.location_district[:15]}",
            callback_data=f"prop_action:view:{prop.id}",
        )
    builder.adjust(1)

    from aiogram.types import InlineKeyboardMarkup
    # Combine nav and prop buttons
    nav_buttons = kb.inline_keyboard
    prop_buttons = builder.as_markup().inline_keyboard
    combined = InlineKeyboardMarkup(inline_keyboard=prop_buttons + nav_buttons)

    if send:
        await event.answer(text, reply_markup=combined)
    elif edit:
        await event.edit_text(text, reply_markup=combined)
    else:
        await event.answer(text, reply_markup=combined)


@router.callback_query(F.data.startswith("prop_action:"))
async def prop_action(callback: CallbackQuery, db_user: User, bot: Bot):
    parts = callback.data.split(":")
    action = parts[1]
    property_id = int(parts[2])

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        prop = await repo.get_by_id(property_id)

        if not prop:
            await callback.answer("Uy topilmadi", show_alert=True)
            return

        if action == "view":
            settings_repo = SettingsRepository(session)
            rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
            card = format_property_card(prop, rate)
            kb = property_actions_kb(property_id)
            if prop.media:
                await callback.message.answer_photo(photo=prop.media[0].file_id, caption=card, reply_markup=kb)
            else:
                await callback.message.answer(card, reply_markup=kb)

        elif action == "status":
            await callback.message.answer(
                "Yangi statusni tanlang:",
                reply_markup=property_status_kb(property_id),
            )

        elif action == "delete":
            await callback.message.answer(
                t("prop_delete_confirm"),
                reply_markup=delete_confirm_kb(property_id),
            )

        elif action == "publish":
            publisher = PublisherService(session, bot)
            success, msg = await publisher.publish(property_id)
            await callback.message.answer(msg)

    await callback.answer()


@router.callback_query(F.data.startswith("prop_setstatus:"))
async def set_property_status(callback: CallbackQuery, db_user: User):
    parts = callback.data.split(":")
    property_id = int(parts[1])
    new_status = PropertyStatus(parts[2])

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        await repo.update_status(property_id, new_status)

    status_label = t(f"prop_status_{new_status.value}")
    await callback.answer(f"Status yangilandi: {status_label}", show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data.startswith("prop_confirm_delete:"))
async def confirm_delete(callback: CallbackQuery, db_user: User):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        prop = await repo.get_by_id(property_id)
        if prop:
            await session.delete(prop)
            await session.commit()

    await callback.answer(t("prop_deleted"), show_alert=True)
    await callback.message.delete()
