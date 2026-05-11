import math
from decimal import Decimal

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import User, UserRole, PropertyStatus, PropertyType, Property
from src.db.session import AsyncSessionFactory
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.keyboards.agent import (
    my_properties_nav_kb, property_actions_kb, property_status_kb,
    delete_confirm_kb, edit_property_fields_kb, type_select_existing_kb,
)
from src.bot.states.edit_property import EditExistingPropertyStates
from src.bot.filters.role import RoleFilter
from src.bot.utils.property_media import answer_property_media_card
from src.services.publisher_service import PublisherService
from src.utils.formatters import format_property_card, PROPERTY_TYPE_ICONS
from locales.uz import t

EDIT_FIELD_PROMPTS = {
    "location_district": "📍 Yangi tuman nomini kiriting:",
    "location_address":  "🏠 Yangi manzilni kiriting (yoki /skip):",
    "rooms":             "🚪 Yangi xonalar sonini kiriting (raqam):",
    "floor":             "🏢 Yangi qavat raqamini kiriting (yoki /skip):",
    "total_floors":      "🏢 Yangi jami qavatlar sonini kiriting (yoki /skip):",
    "area_sqm":          "📐 Yangi maydonni m² da kiriting (yoki /skip):",
    "price_usd":         "💰 Yangi narxni USD da kiriting (raqam):",
    "description":       "📝 Yangi tavsifni kiriting:",
}
EDIT_INT_FIELDS = {"rooms", "floor", "total_floors"}


def _owns_property(prop: "Property", db_user: "User") -> bool:
    """True if user is allowed to mutate this property."""
    if db_user.role == UserRole.developer:
        return True
    if db_user.role == UserRole.director:
        return prop.company_id == db_user.company_id
    return prop.agent_id == db_user.id


async def get_property_for_agent(
    property_id: int,
    agent: User,
    session: AsyncSession,
) -> Property | None:
    """Return a property only when the current agent owns it."""
    result = await session.execute(
        select(Property)
        .where(
            Property.id == property_id,
            Property.agent_id == agent.id,
        )
        .options(
            selectinload(Property.media),
            selectinload(Property.agent),
        )
    )
    return result.scalar_one_or_none()


async def get_property_for_actor(
    property_id: int,
    db_user: User,
    session: AsyncSession,
) -> Property | None:
    if db_user.role == UserRole.agent:
        return await get_property_for_agent(property_id, db_user, session)

    result = await session.execute(
        select(Property)
        .where(Property.id == property_id)
        .options(
            selectinload(Property.media),
            selectinload(Property.agent),
        )
    )
    prop = result.scalar_one_or_none()
    return prop if prop and _owns_property(prop, db_user) else None


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
        prop = await get_property_for_actor(property_id, db_user, session)

        if not prop:
            await callback.answer("❌ Bunday obyekt topilmadi yoki sizniki emas", show_alert=True)
            return

        if action == "view":
            settings_repo = SettingsRepository(session)
            rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
            card = format_property_card(prop, rate)
            await answer_property_media_card(
                callback.message,
                media_items=prop.media,
                caption=card,
                reply_markup=property_actions_kb(property_id),
                parse_mode="HTML",
                caption_entities_json=prop.custom_text_entities_json if prop.custom_text else None,
            )

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

        elif action == "edit":
            await callback.message.answer(
                "✏️ Qaysi maydonni o'zgartirmoqchisiz?",
                reply_markup=edit_property_fields_kb(property_id),
            )

        elif action == "publish":
            publisher = PublisherService(session, bot)
            success, msg = await publisher.publish(property_id)
            await callback.message.answer(msg)

    await callback.answer()


# ─── Edit existing property ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("edit_prop_field:"))
async def start_edit_field(callback: CallbackQuery, state: FSMContext, db_user: User):
    _, prop_id_str, field = callback.data.split(":", 2)
    prop_id = int(prop_id_str)

    async with AsyncSessionFactory() as session:
        prop = await get_property_for_actor(prop_id, db_user, session)
        if not prop:
            await callback.answer("❌ Bunday obyekt topilmadi yoki sizniki emas", show_alert=True)
            return

    if field == "property_type":
        await callback.message.answer(
            "Yangi turni tanlang:", reply_markup=type_select_existing_kb(prop_id)
        )
        await callback.answer()
        return

    await state.set_state(EditExistingPropertyStates.entering_field_value)
    await state.update_data(edit_prop_id=prop_id, edit_field=field)
    await callback.message.answer(EDIT_FIELD_PROMPTS.get(field, f"{field} kiriting:"))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_prop_type:"))
async def save_prop_type(callback: CallbackQuery, db_user: User):
    _, prop_id_str, ptype = callback.data.split(":", 2)
    prop_id = int(prop_id_str)

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update as sa_update
        prop = await get_property_for_actor(prop_id, db_user, session)
        if not prop:
            await callback.answer("❌ Bunday obyekt topilmadi yoki sizniki emas", show_alert=True)
            return
        await session.execute(
            sa_update(Property)
            .where(Property.id == prop_id)
            .values(property_type=PropertyType(ptype))
        )
        await session.commit()

    await callback.answer("✅ Tur yangilandi", show_alert=True)
    await callback.message.answer(
        "✏️ Boshqa maydonni o'zgartirish:", reply_markup=edit_property_fields_kb(prop_id)
    )


@router.message(EditExistingPropertyStates.entering_field_value, F.text)
async def save_edit_field_value(message: Message, state: FSMContext, db_user: User):
    data = await state.get_data()
    prop_id: int = data["edit_prop_id"]
    field: str = data["edit_field"]
    raw = message.text.strip()

    if raw == "/skip":
        value = None
    elif field in EDIT_INT_FIELDS:
        try:
            value = int(raw.replace(",", "").replace(" ", "").split(".")[0])
        except ValueError:
            await message.answer("❌ Raqam kiriting.")
            return
    elif field == "price_usd":
        try:
            value = Decimal(raw.replace(",", "").replace(" ", ""))
        except Exception:
            await message.answer("❌ Raqam kiriting. Misol: 65000")
            return
    elif field == "area_sqm":
        try:
            value = Decimal(raw.replace(",", "."))
        except Exception:
            await message.answer("❌ Raqam kiriting. Misol: 75.5")
            return
    else:
        value = raw

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update as sa_update
        prop = await get_property_for_actor(prop_id, db_user, session)
        if not prop:
            await message.answer("❌ Bunday obyekt topilmadi yoki sizniki emas")
            await state.clear()
            return
        await session.execute(
            sa_update(Property).where(Property.id == prop_id).values(**{field: value})
        )
        await session.commit()

    await state.clear()
    await message.answer("✅ Yangilandi!", reply_markup=edit_property_fields_kb(prop_id))


@router.callback_query(F.data.startswith("prop_setstatus:"))
async def set_property_status(callback: CallbackQuery, db_user: User):
    parts = callback.data.split(":")
    property_id = int(parts[1])
    new_status = PropertyStatus(parts[2])

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        prop = await get_property_for_actor(property_id, db_user, session)
        if not prop:
            await callback.answer("❌ Bunday obyekt topilmadi yoki sizniki emas", show_alert=True)
            return
        await repo.update_status(property_id, new_status)

    status_label = t(f"prop_status_{new_status.value}")
    await callback.answer(f"Status yangilandi: {status_label}", show_alert=True)
    await callback.message.delete()


@router.callback_query(F.data.startswith("prop_confirm_delete:"))
async def confirm_delete(callback: CallbackQuery, db_user: User):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        prop = await get_property_for_actor(property_id, db_user, session)
        if not prop:
            await callback.answer("❌ Bunday obyekt topilmadi yoki sizniki emas", show_alert=True)
            return
        await session.delete(prop)
        await session.commit()

    await callback.answer(t("prop_deleted"), show_alert=True)
    await callback.message.delete()
