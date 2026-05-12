"""Agent — add new property (step-by-step FSM with AI description generation)."""
import asyncio
import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import pytz
import structlog
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.bot.filters.role import RoleFilter
from src.bot.keyboards.agent import (
    property_type_kb, district_kb, rooms_kb, area_kb, price_range_kb,
    features_kb, media_done_kb, preview_action_kb, publish_options_kb,
    publish_date_kb, publish_time_kb, skip_kb,
)
from src.bot.states.add_property import AddPropertyStates
from src.bot.utils.message_entities import dump_message_entities, load_message_entities
from src.bot.utils.property_media import answer_property_media_card
from src.config import settings
from src.db.models import (
    Company, FileType, Property, PropertyMedia, PropertyStatus, PropertyType,
    ScheduledPost, ScheduledPostStatus, User, UserRole,
)
from src.db.repositories.settings_repo import SettingsRepository
from src.db.session import AsyncSessionFactory
from src.services.ai_service import (
    generate_property_description,
    generate_property_title,
    evaluate_photo_quality_from_bytes,
)
from src.services.publisher_service import PublisherService
from src.utils.currency import usd_to_uzs
from locales.uz import t

logger = structlog.get_logger()

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))

# Default districts shown when DB has no prior properties yet
_DEFAULT_DISTRICTS = [
    "Mirzo Ulug'bek", "Yunusobod", "Chilonzor", "Yakkasaroy",
    "Uchtepa", "Olmazor", "Shayxontohur", "Almazar",
    "Yashnobod", "Sergeli",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_districts(company_id: Optional[int]) -> list[str]:
    """Return distinct districts already used by this company, fallback to defaults."""
    from sqlalchemy import select
    async with AsyncSessionFactory() as session:
        q = select(Property.location_district).distinct()
        if company_id:
            q = q.where(Property.company_id == company_id)
        rows = (await session.execute(q)).scalars().all()
    districts = [r for r in rows if r]
    return districts or _DEFAULT_DISTRICTS


async def _get_company_id(db_user: User) -> Optional[int]:
    if db_user.company_id:
        return db_user.company_id
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        company = (await session.execute(select(Company).limit(1))).scalar_one_or_none()
        return company.id if company else None


def _build_preview_text(data: dict) -> str:
    """Format property preview card from FSM data dict."""
    ptype_labels = {"apartment": "🏢 Kvartira", "house": "🏡 Hovli", "commercial": "🏪 Tijorat"}
    ptype = ptype_labels.get(data.get("property_type", ""), "❓")
    district = data.get("district") or "—"
    address = data.get("address") or "—"
    rooms = data.get("rooms") or "—"
    floor = data.get("floor")
    total_floors = data.get("total_floors")
    area = data.get("area_sqm")
    price = data.get("price_usd")
    features: list = data.get("features", [])
    description = data.get("description") or "—"

    floor_str = f"{floor}/{total_floors}" if floor and total_floors else (str(floor) if floor else "—")
    area_str = f"{area} m²" if area else "—"
    price_str = f"${int(price):,}" if price else "❓"

    from src.bot.keyboards.agent import FEATURES
    feat_map = dict(FEATURES)
    feat_labels = ", ".join(feat_map.get(f, f) for f in features) if features else "—"

    desc_preview = str(description)[:300] + ("…" if len(str(description)) > 300 else "")
    photos_count = len(data.get("photos", []))
    videos_count = len(data.get("videos", []))

    return (
        f"{t('ap_preview_header')}"
        f"🏠 <b>Tur:</b> {ptype}\n"
        f"📍 <b>Tuman:</b> {district}\n"
        f"🏠 <b>Manzil:</b> {address}\n"
        f"🚪 <b>Xonalar:</b> {rooms}\n"
        f"🏢 <b>Qavat:</b> {floor_str}\n"
        f"📐 <b>Maydon:</b> {area_str}\n"
        f"💰 <b>Narx:</b> {price_str}\n"
        f"✨ <b>Xususiyatlar:</b> {feat_labels}\n"
        f"📸 <b>Rasmlar:</b> {photos_count} ta\n"
        f"📹 <b>Video:</b> {videos_count} ta\n\n"
        f"📝 <b>Tavsif:</b>\n{desc_preview}"
    )


async def _answer_text_with_entities(
    message: Message,
    text: str,
    entities_json: list[dict] | None,
    reply_markup=None,
) -> None:
    entities = load_message_entities(entities_json)
    try:
        await message.answer(
            text,
            entities=entities,
            parse_mode=None,
            reply_markup=reply_markup,
        )
    except Exception as exc:
        logger.warning("preview_entities_send_failed", error=str(exc))
        await message.answer(text, parse_mode=None, reply_markup=reply_markup)


def _preview_media_items(data: dict) -> list[dict]:
    photos = data.get("photos", [])
    videos = data.get("videos", [])
    return [
        *[{"file_id": item["file_id"], "file_type": FileType.photo} for item in photos],
        *[{"file_id": item["file_id"], "file_type": FileType.video} for item in videos],
    ]


async def _show_review_preview(message: Message, data: dict) -> dict | None:
    custom_text = data.get("custom_text")
    if custom_text:
        media_items = _preview_media_items(data)
        entities_json = data.get("custom_text_entities_json")
        if media_items and len(custom_text) <= 1024:
            sent_messages = await answer_property_media_card(
                message,
                media_items=media_items,
                caption=custom_text,
                reply_markup=preview_action_kb(),
                parse_mode=None,
                caption_entities_json=entities_json,
            )
            source_message = sent_messages[0] if sent_messages else None
            if source_message:
                return {
                    "custom_text_source_chat_id": source_message.chat.id,
                    "custom_text_source_message_id": source_message.message_id,
                    "custom_text_source_has_media": True,
                }
            return None

        if media_items:
            await answer_property_media_card(
                message,
                media_items=media_items,
                caption="📸 Yuklangan media",
                parse_mode="HTML",
            )
        await _answer_text_with_entities(
            message,
            custom_text,
            entities_json,
            reply_markup=preview_action_kb(),
        )
        return None

    preview_text = _build_preview_text(data)
    await answer_property_media_card(
        message,
        media_items=_preview_media_items(data),
        caption=preview_text,
        reply_markup=preview_action_kb(),
        parse_mode="HTML",
    )
    return None


async def _score_and_sort_photos(bot: Bot, photos: list[dict]) -> list[dict]:
    """Download each photo and score quality; return sorted best-first."""
    async def _score_one(item: dict) -> dict:
        try:
            tg_file = await bot.get_file(item["file_id"])
            bio = await bot.download_file(tg_file.file_path)
            if hasattr(bio, "read"):
                raw = bio.read()
            else:
                raw = bio
            ext = (tg_file.file_path or "photo.jpg").rsplit(".", 1)[-1].lower()
            score = await evaluate_photo_quality_from_bytes(raw, ext)
        except Exception:
            score = 5.0
        return {**item, "score": score}

    scored = await asyncio.gather(*[_score_one(p) for p in photos])
    return sorted(scored, key=lambda x: x.get("score", 5.0), reverse=True)


# ─── Step 1: Entry → choose property type ────────────────────────────────────

@router.message(F.text == "➕ Yangi uy qo'shish")
async def start_add_property(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AddPropertyStates.choosing_type)
    await message.answer(t("ap_step_type"), reply_markup=property_type_kb())


# ─── Step 1 callback ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_type:"), AddPropertyStates.choosing_type)
async def choose_type(callback: CallbackQuery, state: FSMContext, db_user: User):
    ptype = callback.data.split(":")[1]
    await state.update_data(property_type=ptype, features=[], photos=[], videos=[])

    company_id = await _get_company_id(db_user)
    districts = await _get_districts(company_id)

    await state.set_state(AddPropertyStates.choosing_district)
    await callback.message.edit_text(t("ap_step_district"), reply_markup=district_kb(districts))
    await callback.answer()


# ─── Step 2: District ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_district:"), AddPropertyStates.choosing_district)
async def choose_district(callback: CallbackQuery, state: FSMContext):
    district = callback.data.split(":", 1)[1]
    if district == "__new__":
        await state.set_state(AddPropertyStates.entering_district)
        await callback.message.edit_text(t("ap_enter_district"))
        await callback.answer()
        return

    await state.update_data(district=district)
    await state.set_state(AddPropertyStates.entering_address)
    await callback.message.edit_text(t("ap_step_address"), reply_markup=skip_kb())
    await callback.answer()


@router.message(AddPropertyStates.entering_district, F.text)
async def enter_custom_district(message: Message, state: FSMContext):
    await state.update_data(district=message.text.strip())
    await state.set_state(AddPropertyStates.entering_address)
    await message.answer(t("ap_step_address"), reply_markup=skip_kb())


# ─── Step 3: Address (optional) ───────────────────────────────────────────────

@router.callback_query(F.data == "ap_skip", AddPropertyStates.entering_address)
async def skip_address(callback: CallbackQuery, state: FSMContext):
    await state.update_data(address=None)
    await state.set_state(AddPropertyStates.choosing_rooms)
    await callback.message.edit_text(t("ap_step_rooms"), reply_markup=rooms_kb())
    await callback.answer()


@router.message(AddPropertyStates.entering_address, F.text)
async def enter_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(AddPropertyStates.choosing_rooms)
    await message.answer(t("ap_step_rooms"), reply_markup=rooms_kb())


# ─── Step 4: Rooms ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_rooms:"), AddPropertyStates.choosing_rooms)
async def choose_rooms(callback: CallbackQuery, state: FSMContext):
    rooms_val = callback.data.split(":")[1]
    rooms = None if rooms_val in ("any", "5+") else int(rooms_val)
    if rooms_val == "5+":
        rooms = 5
    await state.update_data(rooms=rooms)

    data = await state.get_data()
    ptype = data.get("property_type")

    if ptype == "apartment":
        await state.set_state(AddPropertyStates.entering_floor)
        await callback.message.edit_text(t("ap_step_floor"))
    else:
        # Skip floor for house/commercial
        await state.set_state(AddPropertyStates.choosing_area)
        await callback.message.edit_text(t("ap_step_area"), reply_markup=area_kb())
    await callback.answer()


# ─── Step 5: Floor (apartments only) ──────────────────────────────────────────

@router.message(AddPropertyStates.entering_floor, F.text)
async def enter_floor(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ("/skip", "skip", "o'tkazib"):
        await state.update_data(floor=None, total_floors=None)
        await state.set_state(AddPropertyStates.choosing_area)
        await message.answer(t("ap_step_area"), reply_markup=area_kb())
        return
    try:
        floor = int(text)
    except ValueError:
        await message.answer(t("ap_floor_error"))
        return
    await state.update_data(floor=floor)
    await state.set_state(AddPropertyStates.entering_total_floors)
    await message.answer(t("ap_step_total_floors"))


@router.message(AddPropertyStates.entering_total_floors, F.text)
async def enter_total_floors(message: Message, state: FSMContext):
    text = message.text.strip()
    if text.lower() in ("/skip", "skip"):
        await state.update_data(total_floors=None)
    else:
        try:
            await state.update_data(total_floors=int(text))
        except ValueError:
            await message.answer(t("ap_floor_error"))
            return
    await state.set_state(AddPropertyStates.choosing_area)
    await message.answer(t("ap_step_area"), reply_markup=area_kb())


# ─── Step 6: Area ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_area:"), AddPropertyStates.choosing_area)
async def choose_area(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "skip":
        await state.update_data(area_sqm=None)
        await state.set_state(AddPropertyStates.choosing_price)
        await callback.message.edit_text(t("ap_step_price"), reply_markup=price_range_kb())
        await callback.answer()
        return
    if val == "custom":
        await state.set_state(AddPropertyStates.entering_area)
        await callback.message.edit_text(t("ap_enter_area"))
        await callback.answer()
        return
    # preset: "40", "60", "80", "100", "120", "150+"
    numeric = val.rstrip("+")
    try:
        area = float(numeric)
    except ValueError:
        area = None
    await state.update_data(area_sqm=area)
    await state.set_state(AddPropertyStates.choosing_price)
    await callback.message.edit_text(t("ap_step_price"), reply_markup=price_range_kb())
    await callback.answer()


@router.message(AddPropertyStates.entering_area, F.text)
async def enter_area(message: Message, state: FSMContext):
    try:
        area = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("❌ Raqam kiriting. Misol: 75")
        return
    await state.update_data(area_sqm=area)
    await state.set_state(AddPropertyStates.choosing_price)
    await message.answer(t("ap_step_price"), reply_markup=price_range_kb())


# ─── Step 7: Price ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_price:"), AddPropertyStates.choosing_price)
async def choose_price(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "custom":
        await state.set_state(AddPropertyStates.entering_price)
        await callback.message.edit_text(t("ap_enter_price"))
        await callback.answer()
        return
    try:
        price = int(val)
    except ValueError:
        await callback.answer("❌ Xato", show_alert=True)
        return
    await state.update_data(price_usd=price)
    await state.set_state(AddPropertyStates.choosing_features)
    data = await state.get_data()
    await callback.message.edit_text(
        t("ap_step_features"),
        reply_markup=features_kb(data.get("features", [])),
    )
    await callback.answer()


@router.message(AddPropertyStates.entering_price, F.text)
async def enter_price(message: Message, state: FSMContext):
    raw = message.text.strip().replace(",", "").replace(" ", "")
    try:
        price = int(raw)
    except ValueError:
        await message.answer(t("ap_price_error"))
        return
    await state.update_data(price_usd=price)
    await state.set_state(AddPropertyStates.choosing_features)
    data = await state.get_data()
    await message.answer(
        t("ap_step_features"),
        reply_markup=features_kb(data.get("features", [])),
    )


# ─── Step 8: Features (multi-select) ──────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_feat:"), AddPropertyStates.choosing_features)
async def toggle_feature(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    data = await state.get_data()
    selected: list = list(data.get("features", []))

    if key == "done":
        await state.set_state(AddPropertyStates.entering_keywords)
        await callback.message.edit_text(t("ap_step_keywords"), reply_markup=skip_kb())
        await callback.answer()
        return

    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(features=selected)
    await callback.message.edit_reply_markup(reply_markup=features_kb(selected))
    await callback.answer()


# ─── Step 9: Keywords (optional) ──────────────────────────────────────────────

@router.callback_query(F.data == "ap_skip", AddPropertyStates.entering_keywords)
async def skip_keywords(callback: CallbackQuery, state: FSMContext):
    await state.update_data(keywords=None)
    await state.set_state(AddPropertyStates.uploading_media)
    data = await state.get_data()
    photo_count = len(data.get("photos", []))
    video_count = len(data.get("videos", []))
    await callback.message.edit_text(t("ap_step_media"), reply_markup=media_done_kb(photo_count, video_count))
    await callback.answer()


@router.message(AddPropertyStates.entering_keywords, F.text)
async def enter_keywords(message: Message, state: FSMContext):
    await state.update_data(keywords=message.text.strip())
    await state.set_state(AddPropertyStates.uploading_media)
    data = await state.get_data()
    photo_count = len(data.get("photos", []))
    video_count = len(data.get("videos", []))
    await message.answer(t("ap_step_media"), reply_markup=media_done_kb(photo_count, video_count))


# ─── Step 10: Upload media ─────────────────────────────────────────────────────

@router.message(AddPropertyStates.uploading_media, F.photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos: list = list(data.get("photos", []))
    videos: list = list(data.get("videos", []))

    if len(photos) >= 10:
        await message.answer(t("ap_media_limit_photo"), reply_markup=media_done_kb(len(photos), len(videos)))
        return

    photos.append({"file_id": message.photo[-1].file_id})
    await state.update_data(photos=photos)
    await message.answer(t("ap_media_received", count=len(photos)), reply_markup=media_done_kb(len(photos), len(videos)))


@router.message(AddPropertyStates.uploading_media, F.video | F.document)
async def receive_video(message: Message, state: FSMContext):
    data = await state.get_data()
    photos: list = list(data.get("photos", []))
    videos: list = list(data.get("videos", []))

    if len(videos) >= 2:
        await message.answer(t("ap_media_limit_video"), reply_markup=media_done_kb(len(photos), len(videos)))
        return

    file_id = message.video.file_id if message.video else message.document.file_id
    videos.append({"file_id": file_id})
    await state.update_data(videos=videos)
    await message.answer(t("ap_video_received", count=len(videos)), reply_markup=media_done_kb(len(photos), len(videos)))


@router.callback_query(F.data == "ap_media:done", AddPropertyStates.uploading_media)
async def media_done(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: User):
    data = await state.get_data()
    photos: list = data.get("photos", [])
    videos: list = data.get("videos", [])

    if not photos and not videos:
        await callback.answer(t("ap_media_need_one"), show_alert=True)
        return

    await callback.message.edit_text(t("ap_processing"))
    await callback.answer()

    await _run_ai_processing(callback.message, state, bot, db_user, data)


async def _run_ai_processing(message: Message, state: FSMContext, bot: Bot, db_user: User, data: dict):
    """Score photos, generate title + description, show preview."""
    photos: list = data.get("photos", [])

    # Score photos concurrently (with timeout fallback)
    try:
        sorted_photos = await asyncio.wait_for(
            _score_and_sort_photos(bot, photos),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        sorted_photos = photos  # skip scoring if too slow
        logger.warning("photo_scoring_timeout")

    # Build AI input
    from src.bot.keyboards.agent import FEATURES
    feat_map = dict(FEATURES)
    feat_labels = [feat_map.get(f, f) for f in data.get("features", [])]

    ai_data = {
        "property_type": data.get("property_type"),
        "district": data.get("district"),
        "address": data.get("address"),
        "rooms": data.get("rooms"),
        "floor": data.get("floor"),
        "total_floors": data.get("total_floors"),
        "area": data.get("area_sqm"),
        "price": data.get("price_usd"),
        "features": feat_labels,
        "keywords": data.get("keywords"),
    }

    title = generate_property_title(ai_data)

    await state.update_data(
        photos=sorted_photos,
        title=title,
    )

    await state.set_state(AddPropertyStates.entering_description)
    await message.answer(
        "✏️ <b>Tavsif kiriting:</b>\n\n"
        "Obyekt haqida qisqacha tavsif yozing (2-5 gap).\n"
        "Xususiyatlar, joylashuv, afzalliklar haqida yozing.",
        parse_mode="HTML",
    )


# ─── Step 12: Review preview ──────────────────────────────────────────────────

@router.message(AddPropertyStates.entering_description, F.text)
async def description_entered(message: Message, state: FSMContext):
    description = message.text.strip()
    data = await state.get_data()
    await state.update_data(description=description, ai_description=description)
    await state.set_state(AddPropertyStates.reviewing_preview)
    await _show_review_preview(message, {**data, "description": description})


@router.callback_query(F.data == "ap_preview:confirm", AddPropertyStates.reviewing_preview)
async def preview_confirm(callback: CallbackQuery, state: FSMContext, db_user: User, bot: Bot):
    await callback.answer()
    await _save_and_ask_publish(callback.message, state, db_user, bot)


@router.callback_query(F.data == "ap_preview:edit_text", AddPropertyStates.reviewing_preview)
async def preview_edit_text(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddPropertyStates.waiting_custom_text)
    data = await state.get_data()
    await callback.message.answer(
        "Yangi tayyor e'lon matnini yuboring.\n\n"
        "Premium emoji va formatlash saqlanadi."
    )
    await callback.answer()


@router.message(AddPropertyStates.waiting_custom_text, F.text)
async def save_custom_text(message: Message, state: FSMContext, db_user: User, bot: Bot):
    if not message.text or not message.text.strip():
        await message.answer("Matn bo'sh bo'lmasin. Tayyor e'lon matnini yuboring:")
        return

    data = await state.get_data()
    if _preview_media_items(data) and len(message.text) > 1024:
        await message.answer(
            "Media bilan bitta post bo'lishi uchun matn 1024 belgidan oshmasin. "
            "Iltimos, matnni qisqartirib qayta yuboring."
        )
        return

    await state.update_data(
        custom_text=message.text,
        custom_text_entities_json=dump_message_entities(message.entities),
        custom_text_source_chat_id=message.chat.id,
        custom_text_source_message_id=message.message_id,
        custom_text_source_has_media=False,
        description_edited=True,
    )
    await state.set_state(AddPropertyStates.reviewing_preview)
    data = await state.get_data()
    preview_source = await _show_review_preview(message, data)
    if preview_source:
        await state.update_data(**preview_source)


@router.callback_query(F.data == "ap_preview:regen", AddPropertyStates.reviewing_preview)
async def preview_regen(callback: CallbackQuery, state: FSMContext, bot: Bot, db_user: User):
    try:
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=t("ap_processing"))
        else:
            await callback.message.edit_text(t("ap_processing"))
    except Exception:
        await callback.message.answer(t("ap_processing"))
    await callback.answer()

    data = await state.get_data()
    from src.bot.keyboards.agent import FEATURES
    feat_map = dict(FEATURES)
    feat_labels = [feat_map.get(f, f) for f in data.get("features", [])]

    ai_data = {
        "property_type": data.get("property_type"),
        "district": data.get("district"),
        "address": data.get("address"),
        "rooms": data.get("rooms"),
        "floor": data.get("floor"),
        "total_floors": data.get("total_floors"),
        "area": data.get("area_sqm"),
        "price": data.get("price_usd"),
        "features": feat_labels,
        "keywords": data.get("keywords"),
        "style": "alternative",  # hint for AI to vary the style
    }

    new_desc = await generate_property_description(ai_data)
    await state.update_data(
        description=new_desc,
        custom_text=None,
        custom_text_entities_json=None,
        custom_text_source_chat_id=None,
        custom_text_source_message_id=None,
        custom_text_source_has_media=False,
    )
    data["description"] = new_desc
    data.pop("custom_text", None)
    data.pop("custom_text_entities_json", None)
    data.pop("custom_text_source_chat_id", None)
    data.pop("custom_text_source_message_id", None)
    data.pop("custom_text_source_has_media", None)

    await _show_review_preview(callback.message, data)


@router.callback_query(F.data == "ap_preview:cancel", AddPropertyStates.reviewing_preview)
async def preview_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(t("ap_cancelled"))
    await callback.answer()


# ─── Step 12 → 13: Save to DB, then ask publish time ─────────────────────────

async def _save_and_ask_publish(message: Message, state: FSMContext, db_user: User, bot: Bot):
    data = await state.get_data()
    company_id = await _get_company_id(db_user)

    if not company_id:
        await message.answer("❌ Kompaniya topilmadi!")
        await state.clear()
        return

    async with AsyncSessionFactory() as session:
        ptype = PropertyType(data.get("property_type") or "apartment")
        price = data.get("price_usd") or 0
        rooms = data.get("rooms") or 1
        custom_text = data.get("custom_text")

        prop = Property(
            company_id=company_id,
            agent_id=db_user.id,
            title=data.get("title") or f"{ptype.value} — {rooms} xona",
            description=data.get("description"),
            description_edited=bool(data.get("description_edited")),
            custom_text=custom_text,
            custom_text_entities_json=data.get("custom_text_entities_json"),
            custom_text_source_chat_id=data.get("custom_text_source_chat_id"),
            custom_text_source_message_id=data.get("custom_text_source_message_id"),
            custom_text_source_has_media=bool(data.get("custom_text_source_has_media")),
            price_usd=Decimal(str(price)),
            location_district=data.get("district", ""),
            location_address=data.get("address"),
            rooms=int(rooms),
            floor=int(data["floor"]) if data.get("floor") else None,
            total_floors=int(data["total_floors"]) if data.get("total_floors") else None,
            area_sqm=Decimal(str(data["area_sqm"])) if data.get("area_sqm") else None,
            property_type=ptype,
            features=data.get("features") or [],
            status=PropertyStatus.active,
        )
        session.add(prop)
        await session.flush()

        photos: list = data.get("photos", [])
        for i, item in enumerate(photos):
            media = PropertyMedia(
                property_id=prop.id,
                file_id=item["file_id"],
                file_type=FileType.photo,
                order_index=i,
                is_main=(i == 0),
                ai_quality_score=Decimal(str(item.get("score", 5.0))) if "score" in item else None,
            )
            session.add(media)

        for i, item in enumerate(data.get("videos", [])):
            session.add(PropertyMedia(
                property_id=prop.id,
                file_id=item["file_id"],
                file_type=FileType.video,
                order_index=len(photos) + i,
            ))

        await session.commit()
        prop_id = prop.id

    await state.update_data(saved_prop_id=prop_id)
    await state.set_state(AddPropertyStates.choosing_publish_date)
    await message.answer(
        f"✅ Uy saqlandi (#{prop_id})\n\n🚀 Endi nima qilamiz?",
        reply_markup=publish_options_kb(prop_id),
    )


# ─── Step 13: Publish options ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_pub:"))
async def choose_publish_option(callback: CallbackQuery, state: FSMContext, db_user: User, bot: Bot):
    parts = callback.data.split(":")
    action = parts[1]
    data = await state.get_data()
    prop_id = data.get("saved_prop_id")
    if len(parts) >= 3:
        try:
            prop_id = int(parts[2])
            await state.update_data(saved_prop_id=prop_id)
        except ValueError:
            await callback.answer("❌ Uy ID noto'g'ri", show_alert=True)
            return

    if not prop_id:
        await callback.answer("❌ Uy topilmadi. Qaytadan urinib ko'ring.", show_alert=True)
        return

    if action == "save_only":
        await state.clear()
        await callback.message.answer(t("ap_saved_only"))
        await callback.answer()
        return

    if action == "now":
        await callback.answer()
        async with AsyncSessionFactory() as session:
            publisher = PublisherService(session, bot)
            success, msg = await publisher.publish(prop_id)
        await state.clear()
        await callback.message.answer(msg)
        return

    if action == "schedule":
        await state.set_state(AddPropertyStates.choosing_publish_date)
        await state.update_data(saved_prop_id=prop_id)
        await callback.message.edit_text(t("ap_step_pub_date"), reply_markup=publish_date_kb())
        await callback.answer()


# ─── Step 13a: Choose date ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_date:"), AddPropertyStates.choosing_publish_date)
async def choose_pub_date(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "custom":
        await state.set_state(AddPropertyStates.entering_schedule_datetime)
        await callback.message.edit_text(t("ap_enter_pub_date"))
        await callback.answer()
        return

    try:
        chosen_date = date.fromisoformat(val)
    except ValueError:
        await callback.answer("❌ Xato", show_alert=True)
        return

    await state.update_data(scheduled_date=val)
    await state.set_state(AddPropertyStates.choosing_publish_time)
    await callback.message.edit_text(
        f"📅 {chosen_date.strftime('%d.%m.%Y')}\n\n{t('ap_step_pub_time')}",
        reply_markup=publish_time_kb(),
    )
    await callback.answer()


# ─── Step 13b: Choose time ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ap_time:"), AddPropertyStates.choosing_publish_time)
async def choose_pub_time(callback: CallbackQuery, state: FSMContext, db_user: User):
    val = callback.data.split(":")[1]
    data = await state.get_data()

    if val == "custom":
        await state.set_state(AddPropertyStates.entering_schedule_datetime)
        await callback.message.edit_text(t("ap_enter_pub_time"))
        await callback.answer()
        return

    scheduled_date = data.get("scheduled_date")
    if not scheduled_date:
        await callback.answer("❌ Sana tanlanmadi", show_alert=True)
        return

    dt_str = f"{scheduled_date} {val}"
    try:
        tz = pytz.timezone(settings.TIMEZONE)
        dt = tz.localize(datetime.strptime(dt_str, "%Y-%m-%d %H:%M"))
    except Exception:
        await callback.answer("❌ Xato", show_alert=True)
        return

    await _create_scheduled_post(data["saved_prop_id"], dt)
    await state.clear()
    await callback.message.answer(t("ap_scheduled_ok", dt=dt.strftime("%d.%m.%Y %H:%M")))
    await callback.answer()


# ─── Step 13c: Manual datetime entry ─────────────────────────────────────────

@router.message(AddPropertyStates.entering_schedule_datetime, F.text)
async def enter_schedule_datetime(message: Message, state: FSMContext):
    data = await state.get_data()
    text = message.text.strip()

    # Try to detect if user entered date-only or date+time
    tz = pytz.timezone(settings.TIMEZONE)
    dt = None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%d.%m.%Y":
                # default time 09:00
                parsed = parsed.replace(hour=9, minute=0)
            dt = tz.localize(parsed)
            break
        except ValueError:
            continue

    if not dt:
        # They might be entering just a time after picking a date
        saved_date = data.get("scheduled_date")
        if saved_date:
            try:
                dt_str = f"{saved_date} {text}"
                dt = tz.localize(datetime.strptime(dt_str, "%Y-%m-%d %H:%M"))
            except Exception:
                pass

    if not dt:
        await message.answer(t("ap_date_error"))
        return

    await _create_scheduled_post(data["saved_prop_id"], dt)
    await state.clear()
    await message.answer(t("ap_scheduled_ok", dt=dt.strftime("%d.%m.%Y %H:%M")))


async def _create_scheduled_post(prop_id: int, dt: datetime):
    async with AsyncSessionFactory() as session:
        session.add(ScheduledPost(
            property_id=prop_id,
            scheduled_at=dt,
            status=ScheduledPostStatus.pending,
        ))
        await session.commit()


# ─── Global cancel handler ────────────────────────────────────────────────────

@router.callback_query(F.data == "parsed_cancel")
async def cancel_add_any(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(t("ap_cancelled"))
    await callback.answer()
