from datetime import datetime
from decimal import Decimal

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import (
    User, UserRole, Property, PropertyType, PropertyStatus,
    PropertyMedia, FileType, Company,
)
from src.db.session import AsyncSessionFactory
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.states.add_property import AddPropertyStates
from src.bot.keyboards.agent import publish_time_kb, parsed_preview_kb, type_select_kb
from src.bot.filters.role import RoleFilter
from src.services.publisher_service import PublisherService
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))

FIELD_PROMPTS = {
    "district": "📍 Tuman nomini kiriting:",
    "address": "🏠 Aniq manzilni kiriting (yoki /skip):",
    "rooms": "🚪 Xonalar sonini kiriting (raqam):",
    "floor": "🏢 Qavat raqamini kiriting (yoki /skip):",
    "total_floors": "🏢 Jami qavatlar sonini kiriting (yoki /skip):",
    "area_sqm": "📐 Maydonni m² da kiriting (yoki /skip):",
    "price_usd": "💰 Narxni USD da kiriting (faqat raqam, masalan: 65000):",
    "description": "📝 Tavsifni kiriting:",
}

NUMERIC_FIELDS = {"rooms": int, "floor": int, "total_floors": int, "price_usd": int}


# ─── Entry point ──────────────────────────────────────────────────────────────

@router.message(F.text == "➕ Yangi uy qo'shish")
async def start_add_property(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddPropertyStates.waiting_content)
    await message.answer(t("add_prop_instruction"))


# ─── Collecting content ───────────────────────────────────────────────────────

@router.message(AddPropertyStates.waiting_content, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos: list = data.get("photos", [])

    if len(photos) >= 10:
        await message.answer("Maksimal 10 ta rasm. /done yozing.")
        return

    photos.append({"file_id": message.photo[-1].file_id})
    updates: dict = {"photos": photos}

    # Caption on the first photo becomes the description text
    if message.caption and not data.get("raw_text"):
        updates["raw_text"] = message.caption

    await state.update_data(**updates)
    await message.answer(t("add_prop_photo_received", count=len(photos)))


@router.message(AddPropertyStates.waiting_content, F.video | F.document)
async def receive_video(message: Message, state: FSMContext):
    data = await state.get_data()
    videos: list = data.get("videos", [])

    if len(videos) >= 2:
        await message.answer("Maksimal 2 ta video. /done yozing.")
        return

    file_id = message.video.file_id if message.video else message.document.file_id
    videos.append({"file_id": file_id})
    await state.update_data(videos=videos)
    await message.answer(f"📹 {len(videos)} ta video qabul qilindi.")


@router.message(AddPropertyStates.waiting_content, F.text, ~Command("done"))
async def receive_text(message: Message, state: FSMContext):
    data = await state.get_data()
    existing = data.get("raw_text", "")
    combined = (existing + "\n" + message.text).strip() if existing else message.text
    await state.update_data(raw_text=combined)
    await message.answer("✅ Matn qabul qilindi. Rasmlarni yuboring yoki /done yozing.")


@router.message(AddPropertyStates.waiting_content, Command("done"))
async def done_content(message: Message, state: FSMContext):
    data = await state.get_data()
    photos: list = data.get("photos", [])
    raw_text: str = data.get("raw_text", "").strip()

    if not photos:
        await message.answer(t("add_prop_error_no_photos"))
        return
    if not raw_text:
        await message.answer(t("add_prop_error_no_text"))
        return

    wait_msg = await message.answer(t("add_prop_parsing"))

    from src.services.ai_parser import parse_property_from_text
    parsed = await parse_property_from_text(raw_text)
    await state.update_data(**parsed)

    try:
        await wait_msg.delete()
    except Exception:
        pass

    await state.set_state(AddPropertyStates.confirming)
    await _show_preview(message, state)


# ─── Preview ──────────────────────────────────────────────────────────────────

async def _show_preview(event: Message, state: FSMContext):
    data = await state.get_data()

    ptype = data.get("property_type")
    ptype_labels = {
        "apartment": "🏢 Kvartira",
        "house": "🏡 Hovli",
        "commercial": "🏪 Tijorat",
    }
    ptype_label = ptype_labels.get(ptype, "❓ Aniqlanmadi")

    district = data.get("district") or "❓"
    address = data.get("address") or "—"
    rooms = data.get("rooms") or "❓"
    floor = data.get("floor")
    total_floors = data.get("total_floors")
    area = data.get("area_sqm")
    price = data.get("price_usd")
    desc = data.get("description") or "—"

    floor_str = (
        f"{floor}/{total_floors}" if floor and total_floors
        else (str(floor) if floor else "—")
    )
    area_str = f"{area} m²" if area else "—"
    price_str = f"${int(price):,}" if price else "❓"
    desc_preview = str(desc)[:120] + ("..." if len(str(desc)) > 120 else "")

    text = (
        f"📋 <b>Tekshirib ko'ring:</b>\n\n"
        f"🏠 Tur: {ptype_label}\n"
        f"📍 Tuman: {district}\n"
        f"🏠 Manzil: {address}\n"
        f"🚪 Xonalar: {rooms}\n"
        f"🏢 Qavat: {floor_str}\n"
        f"📐 Maydon: {area_str}\n"
        f"💰 Narx: {price_str}\n"
        f"📝 Tavsif: {desc_preview}\n\n"
        f"✏️ Xato bo'lsa, tegishli tugmani bosing."
    )

    photos: list = data.get("photos", [])
    kb = parsed_preview_kb()

    if photos:
        await event.answer_photo(
            photo=photos[0]["file_id"],
            caption=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


# ─── Field editing ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("edit_field:"), AddPropertyStates.confirming)
async def edit_field_start(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":", 1)[1]
    await state.update_data(editing_field_name=field)
    await state.set_state(AddPropertyStates.editing_field)

    if field == "property_type":
        await callback.message.answer("Mulk turini tanlang:", reply_markup=type_select_kb())
    else:
        await callback.message.answer(FIELD_PROMPTS.get(field, f"{field} ni kiriting:"))

    await callback.answer()


@router.callback_query(F.data.startswith("add_prop_type:"), AddPropertyStates.editing_field)
async def edit_type_chosen(callback: CallbackQuery, state: FSMContext):
    ptype = callback.data.split(":")[1]
    await state.update_data(property_type=ptype, editing_field_name=None)
    await state.set_state(AddPropertyStates.confirming)
    await _show_preview(callback.message, state)
    await callback.answer()


@router.message(AddPropertyStates.editing_field, F.text)
async def save_edited_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("editing_field_name")
    value_raw = message.text.strip()

    if value_raw == "/skip":
        await state.update_data(**{field: None, "editing_field_name": None})
        await state.set_state(AddPropertyStates.confirming)
        await _show_preview(message, state)
        return

    if field in NUMERIC_FIELDS:
        try:
            value = NUMERIC_FIELDS[field](
                value_raw.replace(",", "").replace(" ", "").split(".")[0]
            )
        except ValueError:
            await message.answer("❌ Raqam kiriting.")
            return
    elif field == "area_sqm":
        try:
            value = float(value_raw.replace(",", "."))
        except ValueError:
            await message.answer("❌ Raqam kiriting (masalan: 75.5).")
            return
    else:
        value = value_raw

    await state.update_data(**{field: value, "editing_field_name": None})
    await state.set_state(AddPropertyStates.confirming)
    await _show_preview(message, state)


# ─── Confirm / Cancel ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "parsed_cancel", AddPropertyStates.confirming)
async def cancel_add(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data == "parsed_confirm", AddPropertyStates.confirming)
async def confirm_and_save(callback: CallbackQuery, state: FSMContext, db_user: User):
    data = await state.get_data()

    # Validate required fields
    missing = []
    if not data.get("district"):
        missing.append("Tuman")
    if not data.get("price_usd"):
        missing.append("Narx")
    if not data.get("rooms"):
        missing.append("Xonalar soni")

    if missing:
        await callback.answer(
            f"❌ To'ldirilmagan: {', '.join(missing)}", show_alert=True
        )
        return

    async with AsyncSessionFactory() as session:
        company_id = db_user.company_id
        if not company_id:
            from sqlalchemy import select
            company = (
                await session.execute(select(Company).limit(1))
            ).scalar_one_or_none()
            company_id = company.id if company else None

        if not company_id:
            await callback.answer("❌ Kompaniya topilmadi!", show_alert=True)
            return

        ptype = PropertyType(data.get("property_type") or "apartment")
        prop = Property(
            company_id=company_id,
            agent_id=db_user.id,
            title=f"{data.get('district')} — {data.get('rooms')} xona",
            description=data.get("description"),
            price_usd=Decimal(str(data["price_usd"])),
            location_district=data["district"],
            location_address=data.get("address"),
            rooms=int(data["rooms"]),
            floor=int(data["floor"]) if data.get("floor") else None,
            total_floors=int(data["total_floors"]) if data.get("total_floors") else None,
            area_sqm=Decimal(str(data["area_sqm"])) if data.get("area_sqm") else None,
            property_type=ptype,
            status=PropertyStatus.active,
        )
        session.add(prop)
        await session.flush()

        for i, item in enumerate(data.get("photos", [])):
            session.add(PropertyMedia(
                property_id=prop.id,
                file_id=item["file_id"],
                file_type=FileType.photo,
                order_index=i,
            ))
        for i, item in enumerate(data.get("videos", [])):
            session.add(PropertyMedia(
                property_id=prop.id,
                file_id=item["file_id"],
                file_type=FileType.video,
                order_index=len(data.get("photos", [])) + i,
            ))

        await session.commit()
        prop_id = prop.id

    await state.update_data(saved_prop_id=prop_id)
    await state.set_state(AddPropertyStates.choosing_publish_time)
    await callback.message.answer(
        t("add_prop_saved", prop_id=prop_id) + "\n\n" + t("add_prop_when_publish"),
        reply_markup=publish_time_kb(),
    )
    await callback.answer()


# ─── Publish time ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("publish_time:"), AddPropertyStates.choosing_publish_time)
async def choose_publish_time(callback: CallbackQuery, state: FSMContext, db_user: User, bot: Bot):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    prop_id = data.get("saved_prop_id")

    if action == "save_only":
        await state.clear()
        await callback.message.answer(t("published_saved_only"))
        await callback.answer()
        return

    if action == "schedule":
        await state.set_state(AddPropertyStates.entering_schedule_datetime)
        await callback.message.answer(t("schedule_date_prompt"))
        await callback.answer()
        return

    if action == "now":
        async with AsyncSessionFactory() as session:
            publisher = PublisherService(session, bot)
            success, msg = await publisher.publish(prop_id)
        await state.clear()
        await callback.message.answer(msg)
        await callback.answer()


@router.message(AddPropertyStates.entering_schedule_datetime)
async def enter_schedule_datetime(message: Message, state: FSMContext):
    from src.config import settings as cfg
    import pytz

    text = message.text.strip()
    try:
        tz = pytz.timezone(cfg.TIMEZONE)
        dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        dt = tz.localize(dt)
    except ValueError:
        await message.answer(t("schedule_date_error"))
        return

    data = await state.get_data()
    prop_id = data.get("saved_prop_id")

    async with AsyncSessionFactory() as session:
        from src.db.models import ScheduledPost, ScheduledPostStatus
        session.add(ScheduledPost(
            property_id=prop_id,
            scheduled_at=dt,
            status=ScheduledPostStatus.pending,
        ))
        await session.commit()

    await state.clear()
    await message.answer(t("published_scheduled", dt=dt.strftime("%d.%m.%Y %H:%M")))
