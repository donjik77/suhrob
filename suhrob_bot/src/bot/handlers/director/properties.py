import math

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.db.models import User, UserRole, PropertyStatus
from src.db.session import AsyncSessionFactory
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.filters.role import RoleFilter
from src.services.publisher_service import PublisherService
from src.utils.formatters import format_property_card, PROPERTY_TYPE_ICONS
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.director, UserRole.developer))

PAGE_SIZE = 5


# ─── All properties ───────────────────────────────────────────────────────────

@router.message(F.text == "🔵 🏢 Barcha uylar")
async def all_properties(message: Message, db_user: User):
    await _show_company_props_page(message, db_user, page=1, send=True)


@router.callback_query(F.data.startswith("all_props_page:"))
async def paginate_all_props(callback: CallbackQuery, db_user: User):
    page = int(callback.data.split(":")[1])
    await _show_company_props_page(callback.message, db_user, page=page, send=False, edit=True)
    await callback.answer()


async def _show_company_props_page(event, db_user: User, page: int, send: bool, edit: bool = False):
    company_id = await _get_company_id(db_user)
    if not company_id:
        text = "Kompaniya topilmadi."
        if send:
            await event.answer(text)
        return

    offset = (page - 1) * PAGE_SIZE

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        props, total = await repo.get_company_properties(company_id, offset=offset, limit=PAGE_SIZE)

    if not props and page == 1:
        text = t("all_props_empty")
        if send:
            await event.answer(text)
        else:
            await event.edit_text(text)
        return

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    lines = [t("all_props_title", total=total), ""]

    for i, prop in enumerate(props, start=offset + 1):
        icon = PROPERTY_TYPE_ICONS.get(prop.property_type, "🏠")
        status_label = t(f"prop_status_{prop.status.value}")
        agent_name = ""
        if prop.agent:
            agent_name = prop.agent.full_name or prop.agent.username or ""
        lines.append(
            f"{i}. {icon} {prop.location_district}, ${int(prop.price_usd):,}, "
            f"{prop.rooms} xona — {status_label}"
            + (f" | {agent_name}" if agent_name else "")
        )

    text = "\n".join(lines)

    # Navigation
    nav = InlineKeyboardBuilder()
    if page > 1:
        nav.button(text="⬅️", callback_data=f"all_props_page:{page - 1}")
    nav.button(text=f"{page}/{total_pages}", callback_data="noop")
    if page < total_pages:
        nav.button(text="➡️", callback_data=f"all_props_page:{page + 1}")

    # Property buttons
    props_kb = InlineKeyboardBuilder()
    for prop in props:
        props_kb.button(
            text=f"#{prop.id} {prop.location_district[:15]}",
            callback_data=f"all_prop_view:{prop.id}",
        )
    props_kb.adjust(1)

    from aiogram.types import InlineKeyboardMarkup
    combined = InlineKeyboardMarkup(
        inline_keyboard=props_kb.as_markup().inline_keyboard + nav.as_markup().inline_keyboard
    )

    if send:
        await event.answer(text, reply_markup=combined)
    elif edit:
        await event.edit_text(text, reply_markup=combined)


@router.callback_query(F.data.startswith("all_prop_view:"))
async def view_any_property(callback: CallbackQuery, db_user: User, bot: Bot):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        prop = await repo.get_by_id(property_id)

        if not prop:
            await callback.answer("Uy topilmadi", show_alert=True)
            return

        company_id = await _get_company_id(db_user)
        if prop.company_id != company_id:
            await callback.answer("❌ Bu sizning kompaniyangizning obyekti emas", show_alert=True)
            return

        settings_repo = SettingsRepository(session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
        card = format_property_card(prop, rate)

        builder = InlineKeyboardBuilder()
        builder.button(text="📢 E'lon qilish", callback_data=f"all_prop_publish:{property_id}")
        builder.button(text="🗑 O'chirish", callback_data=f"all_prop_delete:{property_id}")
        builder.button(text="⬅️ Orqaga", callback_data="all_props_page:1")
        builder.adjust(2, 1)

        if prop.media:
            await callback.message.answer_photo(
                photo=prop.media[0].file_id,
                caption=card,
                reply_markup=builder.as_markup(),
            )
        else:
            await callback.message.answer(card, reply_markup=builder.as_markup())

    await callback.answer()


@router.callback_query(F.data.startswith("all_prop_publish:"))
async def publish_any(callback: CallbackQuery, bot: Bot):
    property_id = int(callback.data.split(":")[1])
    async with AsyncSessionFactory() as session:
        publisher = PublisherService(session, bot)
        success, msg = await publisher.publish(property_id)
    await callback.message.answer(msg)
    await callback.answer()


@router.callback_query(F.data.startswith("all_prop_delete:"))
async def delete_any(callback: CallbackQuery):
    property_id = int(callback.data.split(":")[1])
    async with AsyncSessionFactory() as session:
        repo = PropertyRepository(session)
        prop = await repo.get_by_id(property_id)
        if prop:
            await session.delete(prop)
            await session.commit()
    await callback.answer("🗑 O'chirildi", show_alert=True)
    await callback.message.delete()


# ─── Full stats ───────────────────────────────────────────────────────────────

@router.message(F.text == "🔵 📈 To'liq statistika")
async def full_stats(message: Message, db_user: User):
    company_id = await _get_company_id(db_user)
    if not company_id:
        await message.answer("Kompaniya topilmadi.")
        return

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select, func
        from src.db.models import Property, User as UserModel

        active = await session.scalar(
            select(func.count()).where(
                Property.company_id == company_id,
                Property.status == PropertyStatus.active,
            )
        )
        sold = await session.scalar(
            select(func.count()).where(
                Property.company_id == company_id,
                Property.status == PropertyStatus.sold,
            )
        )
        hidden = await session.scalar(
            select(func.count()).where(
                Property.company_id == company_id,
                Property.status == PropertyStatus.hidden,
            )
        )

        # Per-agent breakdown
        agent_stats_result = await session.execute(
            select(UserModel.full_name, UserModel.username, func.count(Property.id).label("cnt"))
            .join(Property, Property.agent_id == UserModel.id, isouter=True)
            .where(
                UserModel.company_id == company_id,
                UserModel.role.in_([UserRole.agent, UserRole.director]),
            )
            .group_by(UserModel.id, UserModel.full_name, UserModel.username)
            .order_by(func.count(Property.id).desc())
        )
        agent_rows = agent_stats_result.all()

    lines = [
        f"📈 <b>Kompaniya statistikasi</b>\n",
        f"🏠 Faol uylar: <b>{active or 0}</b>",
        f"✅ Sotilgan: <b>{sold or 0}</b>",
        f"🙈 Yashirilgan: <b>{hidden or 0}</b>",
        f"📦 Jami: <b>{(active or 0) + (sold or 0) + (hidden or 0)}</b>",
        "",
        "👥 <b>Agentlar bo'yicha:</b>",
    ]
    for row in agent_rows:
        name = row.full_name or row.username or "—"
        lines.append(f"• {name}: {row.cnt} ta uy")

    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── Helper ───────────────────────────────────────────────────────────────────

async def _get_company_id(db_user: User) -> int | None:
    if db_user.company_id:
        return db_user.company_id
    # Developer: return first company
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Company
        company = (
            await session.execute(select(Company).limit(1))
        ).scalar_one_or_none()
        return company.id if company else None
