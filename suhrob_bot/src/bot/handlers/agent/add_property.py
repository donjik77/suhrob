from datetime import datetime
from decimal import Decimal

from aiogram import Router, F, Bot
from aiogram.filters import Command, or_f
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import User, UserRole, PropertyType, PropertyMedia, FileType
from src.db.session import AsyncSessionFactory
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.states.add_property import AddPropertyStates
from src.bot.keyboards.agent import add_district_kb, publish_time_kb, preview_kb
from src.bot.filters.role import RoleFilter
from src.services.publisher_service import PublisherService
from src.utils.formatters import format_property_card
from src.utils.parsers import parse_int, parse_decimal
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


@router.message(F.text == "➕ Yangi uy qo'shish")
async def start_add_property(message: Message, state: FSMContext, db_user: User):
    await state.clear()
    await state.set_state(AddPropertyStates.choosing_type)
    await message.answer(
        t("add_prop_type"),
        reply_markup=_type_kb(),
    )


def _type_kb():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🏢 Kvartira", callback_data="add_prop_type:apartment")
    b.button(text="🏡 Hovli", callback_data="add_prop_type:house")
    b.button(text="🏪 Tijorat", callback_data="add_prop_type:commercial")
    b.adjust(3)
    return b.as_markup()


@router.callback_query(F.data.startswith("add_prop_type:"), AddPropertyStates.choosing_type)
async def choose_type(callback: CallbackQuery, state: FSMContext):
    ptype = callback.data.split(":")[1]
    await state.update_data(property_type=ptype)
    await state.set_state(AddPropertyStates.choosing_district)

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Property
        result = await session.execute(
            select(Property.location_district).distinct().order_by(Property.location_district)
        )
        districts = [row[0] for row in result.all()]

    await callback.message.edit_text(
        t("add_prop_district"),
        reply_markup=add_district_kb(districts),
    )


@router.callback_query(F.data.startswith("add_prop_district:"), AddPropertyStates.choosing_district)
async def choose_district(callback: CallbackQuery, state: FSMContext):
    district = callback.data.split(":", 1)[1]
    if district == "__new__":
        await state.set_state(AddPropertyStates.entering_district)
        await callback.message.edit_text("Yangi tuman nomini kiriting:")
        return

    await state.update_data(district=district)
    await state.set_state(AddPropertyStates.entering_address)
    await callback.message.edit_text(t("add_prop_address"))


@router.message(AddPropertyStates.entering_district)
async def enter_new_district(message: Message, state: FSMContext):
    await state.update_data(district=message.text.strip())
    await state.set_state(AddPropertyStates.entering_address)
    await message.answer(t("add_prop_address"))


@router.message(AddPropertyStates.entering_address)
async def enter_address(message: Message, state: FSMContext):
    if message.text != "/skip":
        await state.update_data(address=message.text.strip())
    await state.set_state(AddPropertyStates.entering_rooms)
    await message.answer(t("add_prop_rooms"))


@router.message(AddPropertyStates.entering_rooms)
async def enter_rooms(message: Message, state: FSMContext):
    rooms = parse_int(message.text)
    if rooms is None or rooms < 1:
        await message.answer(t("add_prop_rooms_error"))
        return
    await state.update_data(rooms=rooms)
    await state.set_state(AddPropertyStates.entering_floor)
    await message.answer(t("add_prop_floor"))


@router.message(AddPropertyStates.entering_floor)
async def enter_floor(message: Message, state: FSMContext):
    if message.text != "/skip":
        floor = parse_int(message.text)
        if floor is not None:
            await state.update_data(floor=floor)
    await state.set_state(AddPropertyStates.entering_total_floors)
    await message.answer(t("add_prop_total_floors"))


@router.message(AddPropertyStates.entering_total_floors)
async def enter_total_floors(message: Message, state: FSMContext):
    if message.text != "/skip":
        total = parse_int(message.text)
        if total is not None:
            await state.update_data(total_floors=total)
    await state.set_state(AddPropertyStates.entering_area)
    await message.answer(t("add_prop_area"))


@router.message(AddPropertyStates.entering_area)
async def enter_area(message: Message, state: FSMContext):
    if message.text != "/skip":
        area = parse_decimal(message.text)
        if area is not None:
            await state.update_data(area_sqm=str(area))
    await state.set_state(AddPropertyStates.entering_price)
    await message.answer(t("add_prop_price"))


@router.message(AddPropertyStates.entering_price)
async def enter_price(message: Message, state: FSMContext):
    price = parse_decimal(message.text)
    if price is None or price <= 0:
        await message.answer(t("add_prop_price_error"))
        return
    await state.update_data(price_usd=str(price))
    await state.set_state(AddPropertyStates.entering_description)
    await message.answer(t("add_prop_description"))


@router.message(AddPropertyStates.entering_description)
async def enter_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddPropertyStates.uploading_photos)
    await message.answer(t("add_prop_photos"))


@router.message(AddPropertyStates.uploading_photos, F.photo)
async def upload_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])

    if len(photos) >= 10:
        await message.answer("Maksimal 10 ta rasm. /done yozing.")
        return

    best = message.photo[-1]
    photos.append({"file_id": best.file_id, "file_type": "photo"})
    await state.update_data(photos=photos)
    await message.answer(t("add_prop_photos_count", count=len(photos)))


@router.message(AddPropertyStates.uploading_photos, Command("done"))
async def photos_done(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("photos"):
        await message.answer("Kamida 1 ta rasm yuboring.")
        return
    await state.set_state(AddPropertyStates.uploading_videos)
    await message.answer(t("add_prop_videos"))


@router.message(AddPropertyStates.uploading_videos, F.video | F.document)
async def upload_video(message: Message, state: FSMContext):
    data = await state.get_data()
    videos = data.get("videos", [])

    if len(videos) >= 2:
        await message.answer("Maksimal 2 ta video. /done yozing.")
        return

    if message.video:
        file_id = message.video.file_id
    else:
        file_id = message.document.file_id

    videos.append({"file_id": file_id, "file_type": "video"})
    await state.update_data(videos=videos)
    await message.answer(f"📹 {len(videos)} ta video qabul qilindi.")


@router.message(AddPropertyStates.uploading_videos, or_f(Command("done"), Command("skip")))
async def videos_done(message: Message, state: FSMContext):
    await _show_preview(message, state)


@router.message(AddPropertyStates.uploading_videos, F.text == "/skip")
async def videos_skip(message: Message, state: FSMContext):
    await _show_preview(message, state)


async def _show_preview(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(AddPropertyStates.preview)

    # Build a fake property object for preview
    from src.db.models import Property, PropertyType, PropertyStatus
    from decimal import Decimal

    preview_prop = Property(
        title=f"{data.get('district', '')} — {data.get('rooms', '?')} xona",
        description=data.get("description", ""),
        price_usd=Decimal(data.get("price_usd", "0")),
        location_district=data.get("district", ""),
        location_address=data.get("address"),
        rooms=data.get("rooms", 0),
        floor=data.get("floor"),
        total_floors=data.get("total_floors"),
        area_sqm=Decimal(data["area_sqm"]) if data.get("area_sqm") else None,
        property_type=PropertyType(data.get("property_type", "apartment")),
        status=PropertyStatus.active,
    )

    async with AsyncSessionFactory() as session:
        settings_repo = SettingsRepository(session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

    card = format_property_card(preview_prop, rate)

    photos = data.get("photos", [])
    if photos:
        await message.answer_photo(
            photo=photos[0]["file_id"],
            caption=t("add_prop_preview", card=card),
            reply_markup=preview_kb(),
        )
    else:
        await message.answer(t("add_prop_preview", card=card), reply_markup=preview_kb())


@router.callback_query(F.data == "add_prop_preview:cancel", AddPropertyStates.preview)
async def preview_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Bekor qilindi.")


@router.callback_query(F.data == "add_prop_preview:edit", AddPropertyStates.preview)
async def preview_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddPropertyStates.choosing_type)
    await callback.message.answer(t("add_prop_type"), reply_markup=_type_kb())


@router.callback_query(F.data == "add_prop_preview:confirm", AddPropertyStates.preview)
async def preview_confirm(callback: CallbackQuery, state: FSMContext, db_user: User):
    data = await state.get_data()

    async with AsyncSessionFactory() as session:
        from src.db.models import Property, PropertyType, PropertyStatus, PropertyMedia, FileType
        from src.db.models import Company
        from sqlalchemy import select

        # Get company_id for agent
        company_id = db_user.company_id
        if company_id is None:
            # Developer without company — get first company
            result = await session.execute(select(Company).limit(1))
            company = result.scalar_one_or_none()
            company_id = company.id if company else 1

        prop = Property(
            company_id=company_id,
            agent_id=db_user.id,
            title=f"{data.get('district', '')} — {data.get('rooms', '?')} xona",
            description=data.get("description"),
            price_usd=Decimal(data.get("price_usd", "0")),
            location_district=data.get("district", ""),
            location_address=data.get("address"),
            rooms=data.get("rooms", 0),
            floor=data.get("floor"),
            total_floors=data.get("total_floors"),
            area_sqm=Decimal(data["area_sqm"]) if data.get("area_sqm") else None,
            property_type=PropertyType(data.get("property_type", "apartment")),
            status=PropertyStatus.active,
        )
        session.add(prop)
        await session.flush()

        order = 0
        for item in data.get("photos", []):
            session.add(PropertyMedia(
                property_id=prop.id,
                file_id=item["file_id"],
                file_type=FileType.photo,
                order_index=order,
            ))
            order += 1

        for item in data.get("videos", []):
            session.add(PropertyMedia(
                property_id=prop.id,
                file_id=item["file_id"],
                file_type=FileType.video,
                order_index=order,
            ))
            order += 1

        await session.commit()
        prop_id = prop.id

    await state.update_data(saved_prop_id=prop_id)
    await state.set_state(AddPropertyStates.choosing_publish_time)

    await callback.message.answer(
        t("add_prop_saved", prop_id=prop_id) + "\n\n" + t("add_prop_when_publish"),
        reply_markup=publish_time_kb(),
    )


@router.callback_query(F.data.startswith("publish_time:"), AddPropertyStates.choosing_publish_time)
async def choose_publish_time(callback: CallbackQuery, state: FSMContext, db_user: User, bot: Bot):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    prop_id = data.get("saved_prop_id")

    if action == "save_only":
        await state.clear()
        await callback.message.answer(t("published_saved_only"))
        return

    if action == "schedule":
        await state.set_state(AddPropertyStates.entering_schedule_datetime)
        await callback.message.answer(t("schedule_date_prompt"))
        return

    if action == "now":
        async with AsyncSessionFactory() as session:
            publisher = PublisherService(session, bot)
            success, msg = await publisher.publish(prop_id)

        await state.clear()
        if success:
            await callback.message.answer(msg)
        else:
            await callback.message.answer(f"❌ E'lon qilishda xato: {msg}")


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
        post = ScheduledPost(
            property_id=prop_id,
            scheduled_at=dt,
            status=ScheduledPostStatus.pending,
        )
        session.add(post)
        await session.commit()

    await state.clear()
    await message.answer(t("published_scheduled", dt=dt.strftime("%d.%m.%Y %H:%M")))
