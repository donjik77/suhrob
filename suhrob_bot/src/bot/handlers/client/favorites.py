import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from locales.uz import t
from src.bot.handlers.client.property_access import get_active_property_for_client, resolve_client_company_id
from src.bot.keyboards.client import favorites_kb, main_menu_kb, request_client_phone_kb
from src.bot.utils.property_media import answer_property_media_card
from src.db.models import (
    ClientFavorite,
    Company,
    LeadAssignment,
    LeadStatus,
    Property,
    PropertyStatus,
    User,
)
from src.db.repositories.settings_repo import SettingsRepository
from src.db.session import AsyncSessionFactory
from src.utils.formatters import format_property_card

router = Router()

_PHONE_RE = re.compile(r"^\+?\d[\d\s().-]{6,}$")


class ContactAgentState(StatesGroup):
    waiting_phone = State()


def _extract_phone(message: Message) -> str | None:
    if message.contact and message.contact.phone_number:
        if message.contact.user_id and message.contact.user_id != message.from_user.id:
            return None
        phone = message.contact.phone_number.strip()
        return phone if phone.startswith("+") else f"+{phone}"

    text = (message.text or "").strip()
    if not _PHONE_RE.match(text):
        return None
    return re.sub(r"\s+", " ", text)


async def _connect_client_to_agent(
    *,
    target_message: Message,
    bot,
    db_user: User,
    company: Company | None,
    property_id: int,
    client_phone: str | None = None,
) -> bool:
    company_id = resolve_client_company_id(company, db_user)
    async with AsyncSessionFactory() as session:
        prop = await get_active_property_for_client(
            property_id,
            company_id,
            session,
            with_agent=True,
        )
        if not prop:
            await target_message.answer("Bunday obyekt mavjud emas yoki sotilgan")
            return False

        if not prop.agent:
            await target_message.answer("Agent topilmadi")
            return False

        if client_phone and client_phone != db_user.phone:
            await session.execute(
                update(User)
                .where(User.id == db_user.id)
                .values(phone=client_phone)
            )
            db_user.phone = client_phone

        existing_lead = (
            await session.execute(
                select(LeadAssignment).where(
                    LeadAssignment.client_user_id == db_user.id,
                    LeadAssignment.property_id == prop.id,
                )
            )
        ).scalar_one_or_none()

        if not existing_lead:
            session.add(
                LeadAssignment(
                    client_user_id=db_user.id,
                    agent_user_id=prop.agent_id,
                    property_id=prop.id,
                    status=LeadStatus.new,
                )
            )
            prop.contacts_count += 1

        await session.commit()

        agent = prop.agent
        username_str = f"@{agent.username}" if agent.username else "(username yo'q)"
        phone_str = agent.phone or "(telefon yo'q)"
        name_str = agent.full_name or agent.username or str(agent.telegram_user_id)

        await target_message.answer(
            t("agent_contact", name=name_str, phone=phone_str, username=username_str),
            reply_markup=ReplyKeyboardRemove(),
        )

        try:
            client_name = db_user.full_name or db_user.username or str(db_user.telegram_user_id)
            client_username = f"@{db_user.username}" if db_user.username else "(username yo'q)"
            client_phone_str = client_phone or db_user.phone or "(telefon yo'q)"
            notify_text = (
                t("agent_notify_new_client", client_name=client_name, property_title=prop.title)
                + f"\nTelefon: {client_phone_str}"
                + f"\nTelegram: {client_username}"
            )
            await bot.send_message(chat_id=agent.telegram_user_id, text=notify_text)
        except Exception:
            pass

    return True


@router.message(F.text == t("btn_favorites"))
async def show_favorites(message: Message, db_user: User, company: Company | None):
    company_id = resolve_client_company_id(company, db_user)
    if company_id is None:
        await message.answer("Kompaniya topilmadi.", reply_markup=main_menu_kb())
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(ClientFavorite)
            .where(ClientFavorite.user_id == db_user.id)
            .join(Property, ClientFavorite.property_id == Property.id)
            .where(
                Property.company_id == company_id,
                Property.status == PropertyStatus.active,
            )
            .options(
                selectinload(ClientFavorite.property).selectinload(Property.media),
                selectinload(ClientFavorite.property).selectinload(Property.agent),
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
            if not prop:
                continue
            await session.execute(
                update(Property)
                .where(Property.id == prop.id, Property.company_id == company_id)
                .values(views_count=Property.views_count + 1)
            )
            await answer_property_media_card(
                message,
                media_items=prop.media,
                caption=format_property_card(prop, rate),
                reply_markup=favorites_kb(prop.id),
                parse_mode="HTML",
                caption_entities_json=prop.custom_text_entities_json if prop.custom_text else None,
            )
        await session.commit()


@router.callback_query(F.data.startswith("prop_fav:"))
async def add_to_favorites(callback: CallbackQuery, db_user: User, company: Company | None):
    property_id = int(callback.data.split(":")[1])
    company_id = resolve_client_company_id(company, db_user)

    async with AsyncSessionFactory() as session:
        prop = await get_active_property_for_client(property_id, company_id, session)
        if not prop:
            await callback.answer("Bunday obyekt mavjud emas yoki sotilgan", show_alert=True)
            return

        existing = await session.execute(
            select(ClientFavorite).where(
                ClientFavorite.user_id == db_user.id,
                ClientFavorite.property_id == property_id,
            )
        )
        if existing.scalar_one_or_none():
            await callback.answer(t("favorite_already"))
            return

        session.add(ClientFavorite(user_id=db_user.id, property_id=property_id))
        await session.commit()

    await callback.answer(t("favorite_saved"), show_alert=True)


@router.callback_query(F.data.startswith("prop_unfav:"))
async def remove_from_favorites(callback: CallbackQuery, db_user: User):
    property_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        await session.execute(
            delete(ClientFavorite).where(
                ClientFavorite.user_id == db_user.id,
                ClientFavorite.property_id == property_id,
            )
        )
        await session.commit()

    await callback.answer(t("favorite_removed"), show_alert=True)
    if callback.message:
        await callback.message.delete()


@router.callback_query(F.data.startswith("prop_contact:"))
async def contact_agent(
    callback: CallbackQuery,
    db_user: User,
    company: Company | None,
    state: FSMContext,
):
    if callback.message is None:
        await callback.answer("Xabar topilmadi", show_alert=True)
        return

    property_id = int(callback.data.split(":")[1])

    if not db_user.phone:
        await state.set_state(ContactAgentState.waiting_phone)
        await state.update_data(property_id=property_id)
        await callback.message.answer(
            "Agent bilan bog'lash uchun telefon raqamingizni yuboring.",
            reply_markup=request_client_phone_kb(),
        )
        await callback.answer()
        return

    await _connect_client_to_agent(
        target_message=callback.message,
        bot=callback.bot,
        db_user=db_user,
        company=company,
        property_id=property_id,
        client_phone=db_user.phone,
    )
    await callback.answer()


@router.message(ContactAgentState.waiting_phone)
async def receive_phone_for_agent(
    message: Message,
    state: FSMContext,
    db_user: User,
    company: Company | None,
):
    phone = _extract_phone(message)
    if not phone:
        await message.answer(
            "Telefon raqam noto'g'ri. Kontakt tugmasi orqali yuboring yoki +998901234567 formatida yozing.",
            reply_markup=request_client_phone_kb(),
        )
        return

    data = await state.get_data()
    property_id = data.get("property_id")
    await state.clear()

    if not property_id:
        await message.answer("Obyekt topilmadi. Iltimos, qaytadan urinib ko'ring.", reply_markup=main_menu_kb())
        return

    await _connect_client_to_agent(
        target_message=message,
        bot=message.bot,
        db_user=db_user,
        company=company,
        property_id=int(property_id),
        client_phone=phone,
    )
