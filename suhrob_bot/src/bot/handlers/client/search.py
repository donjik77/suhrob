from decimal import Decimal
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import update

from src.db.models import User, UserRole, PropertyType, Company, Property, ClientAlert
from src.db.session import AsyncSessionFactory
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.states.search import SearchStates
from src.bot.keyboards.client import (
    search_type_kb, search_district_kb, search_rooms_kb,
    search_price_kb, property_card_kb, search_results_kb, no_results_kb,
)
from src.bot.utils.property_media import answer_property_media_card
from src.services.search_service import SearchService
from src.utils.formatters import format_property_card
from src.utils.parsers import parse_price_range
from locales.uz import t

router = Router()


@router.message(F.text == "🔍 Uy qidirish")
async def start_search(message: Message, state: FSMContext, db_user: User, company: Company):
    if company is None:
        await message.answer("Kompaniya topilmadi.")
        return
    await state.clear()
    await state.update_data(company_id=company.id)
    await state.set_state(SearchStates.choosing_type)
    await message.answer(t("search_type"), reply_markup=search_type_kb())


@router.callback_query(F.data.startswith("search_type:"), SearchStates.choosing_type)
async def choose_type(callback: CallbackQuery, state: FSMContext, company: Company):
    ptype = callback.data.split(":")[1]
    await state.update_data(property_type=ptype)
    await state.set_state(SearchStates.choosing_district)

    data = await state.get_data()
    company_id = data.get("company_id") or (company.id if company else None)
    if company_id is None:
        await callback.answer("Kompaniya topilmadi.", show_alert=True)
        return
    await state.update_data(company_id=company_id)

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Property, PropertyStatus
        q = (
            select(Property.location_district)
            .where(Property.status == PropertyStatus.active)
            .distinct()
            .order_by(Property.location_district)
        )
        if company_id:
            q = q.where(Property.company_id == company_id)
        result = await session.execute(q)
        districts = [row[0] for row in result.all()]

    await callback.message.edit_text(
        t("search_district"),
        reply_markup=search_district_kb(districts),
    )


@router.callback_query(F.data.startswith("search_district:"), SearchStates.choosing_district)
async def choose_district(callback: CallbackQuery, state: FSMContext):
    district = callback.data.split(":", 1)[1]
    if district == "__other__":
        await state.set_state(SearchStates.entering_district)
        await callback.message.edit_text(t("district_input"))
        return

    await state.update_data(district=district)
    await state.set_state(SearchStates.choosing_rooms)
    await callback.message.edit_text(t("search_rooms"), reply_markup=search_rooms_kb())


@router.message(SearchStates.entering_district)
async def enter_district(message: Message, state: FSMContext):
    await state.update_data(district=message.text.strip())
    await state.set_state(SearchStates.choosing_rooms)
    await message.answer(t("search_rooms"), reply_markup=search_rooms_kb())


@router.callback_query(F.data.startswith("search_rooms:"), SearchStates.choosing_rooms)
async def choose_rooms(callback: CallbackQuery, state: FSMContext):
    rooms_val = callback.data.split(":")[1]
    rooms = None if rooms_val == "any" else (5 if rooms_val == "5+" else int(rooms_val))
    await state.update_data(rooms=rooms)
    await state.set_state(SearchStates.choosing_price)
    await callback.message.edit_text(t("search_price"), reply_markup=search_price_kb())


@router.callback_query(F.data.startswith("search_price:"), SearchStates.choosing_price)
async def choose_price(callback: CallbackQuery, state: FSMContext):
    price_val = callback.data.split(":", 1)[1]

    if price_val == "custom":
        await state.set_state(SearchStates.entering_custom_price)
        await callback.message.edit_text(t("price_custom_prompt"))
        return

    parts = price_val.split(":")
    price_min = Decimal(parts[0]) if parts[0] else None
    price_max = Decimal(parts[1]) if len(parts) > 1 and parts[1] else None
    await state.update_data(price_min=str(price_min) if price_min else None, price_max=str(price_max) if price_max else None)

    await _do_search(callback.message, state, edit=True)


@router.message(SearchStates.entering_custom_price)
async def enter_custom_price(message: Message, state: FSMContext):
    price_min, price_max = parse_price_range(message.text)
    if price_min is None and price_max is None:
        await message.answer(t("price_parse_error"))
        return

    await state.update_data(
        price_min=str(price_min) if price_min else None,
        price_max=str(price_max) if price_max else None,
    )
    await _do_search(message, state, edit=False)


async def _do_search(message_or_obj, state: FSMContext, edit: bool = False):
    data = await state.get_data()

    company_id: int = data.get("company_id")
    if company_id is None:
        await message_or_obj.answer("Kompaniya topilmadi.")
        await state.clear()
        return
    district: Optional[str] = data.get("district")
    rooms: Optional[int] = data.get("rooms")
    price_min = Decimal(data["price_min"]) if data.get("price_min") else None
    price_max = Decimal(data["price_max"]) if data.get("price_max") else None
    ptype_str = data.get("property_type")
    ptype = PropertyType(ptype_str) if ptype_str else None

    async with AsyncSessionFactory() as session:
        settings_repo = SettingsRepository(session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", default=12600.0)

        search_svc = SearchService(session)
        props, exact = await search_svc.search(
            company_id=company_id,
            district=district,
            price_min=price_min,
            price_max=price_max,
            rooms=rooms,
            property_type=ptype,
        )

        # Log search request
        # (user_id needs to be threaded; skip for now, added in iteration 5)

    await state.set_state(SearchStates.showing_results)

    # Increment views_count for all displayed properties
    if props:
        prop_ids = [p.id for p in props]
        async with AsyncSessionFactory() as inc_session:
            await inc_session.execute(
                update(Property)
                .where(Property.id.in_(prop_ids), Property.company_id == company_id)
                .values(views_count=Property.views_count + 1)
            )
            await inc_session.commit()

    if not props:
        text = t("results_none")
        kb = no_results_kb()
        if edit:
            await message_or_obj.edit_text(text, reply_markup=kb)
        else:
            await message_or_obj.answer(text, reply_markup=kb)
        return

    if exact:
        header = t("results_found", count=len(props))
        kb = search_results_kb()
    else:
        header = t("results_not_found")
        kb = no_results_kb()

    if edit:
        await message_or_obj.edit_text(header)
    else:
        await message_or_obj.answer(header)

    for prop in props:
        card_text = format_property_card(prop, rate)
        await answer_property_media_card(
            message_or_obj,
            media_items=prop.media,
            caption=card_text,
            reply_markup=property_card_kb(prop.id),
            parse_mode="HTML",
            caption_entities_json=prop.custom_text_entities_json if prop.custom_text else None,
        )

    # Show navigation keyboard as separate message
    nav_msg = await message_or_obj.answer("—", reply_markup=kb)


# Back navigation handlers
@router.callback_query(F.data.startswith("search_back:"))
async def search_back(callback: CallbackQuery, state: FSMContext, company: Company):
    target = callback.data.split(":")[1]

    if target == "start":
        await state.clear()
        if company is None:
            await callback.answer("Kompaniya topilmadi.", show_alert=True)
            return
        await state.update_data(company_id=company.id)
        await callback.message.edit_text(t("search_type"), reply_markup=search_type_kb())
        await state.set_state(SearchStates.choosing_type)
    elif target == "type":
        await state.set_state(SearchStates.choosing_type)
        await callback.message.edit_text(t("search_type"), reply_markup=search_type_kb())
    elif target == "district":
        await state.set_state(SearchStates.choosing_district)
        back_data = await state.get_data()
        back_company_id = back_data.get("company_id") or (company.id if company else None)
        if back_company_id is None:
            await callback.answer("Kompaniya topilmadi.", show_alert=True)
            return
        await state.update_data(company_id=back_company_id)
        async with AsyncSessionFactory() as session:
            from sqlalchemy import select
            from src.db.models import Property, PropertyStatus
            q = (
                select(Property.location_district)
                .where(Property.status == PropertyStatus.active)
                .distinct()
                .order_by(Property.location_district)
            )
            if back_company_id:
                q = q.where(Property.company_id == back_company_id)
            result = await session.execute(q)
            districts = [row[0] for row in result.all()]
        await callback.message.edit_text(t("search_district"), reply_markup=search_district_kb(districts))
    elif target == "rooms":
        await state.set_state(SearchStates.choosing_rooms)
        await callback.message.edit_text(t("search_rooms"), reply_markup=search_rooms_kb())


@router.callback_query(F.data == "search_new")
async def new_search(callback: CallbackQuery, state: FSMContext, company: Company):
    await state.clear()
    if company is None:
        await callback.answer("Kompaniya topilmadi.", show_alert=True)
        return
    await state.update_data(company_id=company.id)
    await state.set_state(SearchStates.choosing_type)
    await callback.message.answer(t("search_type"), reply_markup=search_type_kb())


@router.callback_query(F.data == "search_notify")
async def notify_on_new(callback: CallbackQuery, state: FSMContext, db_user: User):
    data = await state.get_data()
    if not data.get("company_id"):
        await callback.answer("Avval qidiruv parametrlarini tanlang.", show_alert=True)
        return

    district = data.get("district")
    price_max_raw = data.get("price_max")
    rooms = data.get("rooms")
    prop_type = data.get("property_type")
    price_max = Decimal(price_max_raw) if price_max_raw else None

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select

        existing = (
            await session.execute(
                select(ClientAlert).where(
                    ClientAlert.user_id == db_user.id,
                    ClientAlert.is_active == True,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.location_district = district
            existing.price_max_usd = price_max
            existing.rooms = rooms
            existing.property_type = prop_type
            existing.last_notified_at = None
        else:
            session.add(
                ClientAlert(
                    user_id=db_user.id,
                    location_district=district,
                    price_max_usd=price_max,
                    rooms=rooms,
                    property_type=prop_type,
                    is_active=True,
                )
            )
        await session.commit()

    price_text = f"${int(price_max)}" if price_max else "istalgan"
    rooms_text = f"{rooms} xona" if rooms else "istalgan"
    await callback.message.edit_text(
        "🔔 <b>Bildirishnoma yoqildi</b>\n\n"
        "Yangi mos uy chiqsa, sizga xabar beramiz.\n\n"
        f"📍 Tuman: {district or 'istalgan'}\n"
        f"💰 Narx (max): {price_text}\n"
        f"🚪 Xonalar: {rooms_text}\n\n"
        "Bekor qilish uchun /unsubscribe yozing.",
    )
    await callback.answer("Bildirishnoma yoqildi ✅", show_alert=True)
