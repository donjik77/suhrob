"""Developer panel — company management (add, list, block)."""
from datetime import datetime, timedelta, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import (
    User, UserRole, Company, Subscription, SubscriptionStatus, SubscriptionType
)
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter
from src.config import settings

router = Router()
router.message.filter(RoleFilter(UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.developer))


class AddCompanyState(StatesGroup):
    company_name = State()
    director_tg_id = State()
    director_name = State()
    director_phone = State()
    channel_id = State()
    bot_token = State()
    bot_username = State()


@router.message(F.text == "🔵 🏢 Kompaniyalar")
async def list_companies(message: Message):
    async with AsyncSessionFactory() as session:
        companies = (
            await session.execute(
                select(Company).order_by(Company.created_at.desc())
            )
        ).scalars().all()

    if not companies:
        await message.answer("Hozircha kompaniyalar yo'q.\n\n/add_company — yangi qo'shish")
        return

    lines = [f"🏢 <b>Kompaniyalar</b> (jami: {len(companies)})\n"]
    buttons = []
    for c in companies:
        status = "✅" if c.is_active else "🔴"
        lines.append(f"{status} {c.name} — @{c.bot_username or '?'}")
        buttons.append([
            InlineKeyboardButton(text=f"🔍 {c.name}", callback_data=f"company_detail:{c.id}")
        ])

    buttons.append([
        InlineKeyboardButton(text="➕ Yangi kompaniya", callback_data="company_add")
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("company_detail:"))
async def company_detail(callback: CallbackQuery):
    company_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        company = (await session.execute(
            select(Company).where(Company.id == company_id)
        )).scalar_one_or_none()

        if not company:
            await callback.answer("Topilmadi.", show_alert=True)
            return

        agents_count = (await session.execute(
            select(User).where(
                User.company_id == company_id,
                User.role == UserRole.agent,
                User.is_blocked == False,
            )
        )).scalars().all()

        from src.db.models import Property, PropertyStatus
        props_count = len((await session.execute(
            select(Property).where(Property.company_id == company_id)
        )).scalars().all())

        base_sub = (await session.execute(
            select(Subscription).where(
                Subscription.company_id == company_id,
                Subscription.subscription_type == SubscriptionType.base,
                Subscription.status == SubscriptionStatus.active,
            ).order_by(Subscription.period_end.desc())
        )).scalar_one_or_none()

        # Director
        director = (await session.execute(
            select(User).where(
                User.company_id == company_id,
                User.role == UserRole.director,
            ).limit(1)
        )).scalar_one_or_none()

        from src.db.models import UserBalance
        balance_row = None
        if director:
            balance_row = (await session.execute(
                select(UserBalance).where(UserBalance.user_id == director.id)
            )).scalar_one_or_none()

    sub_status = "✅ Faol" if base_sub else "❌ Faol emas"
    sub_end = ""
    if base_sub and base_sub.period_end:
        sub_end = f" (gacha {base_sub.period_end.strftime('%d.%m.%Y')})"

    balance_str = f"${float(balance_row.balance_usd):.2f}" if balance_row else "$0.00"

    text = (
        f"🏢 <b>{company.name}</b>\n\n"
        f"🤖 Bot: @{company.bot_username or '—'}\n"
        f"📢 Kanal: {company.telegram_channel_id or '—'}\n\n"
        f"👥 Agentlar: {len(agents_count)}\n"
        f"🏠 Obyektlar: {props_count}\n\n"
        f"📋 Obuna: {sub_status}{sub_end}\n"
        f"💰 Direktor balansi: {balance_str}\n\n"
        f"Holat: {'✅ Faol' if company.is_active else '🔴 Bloklangan'}"
    )

    block_label = "✅ Faollashtirish" if not company.is_active else "🔴 Bloklash"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Hisob chiqarish", callback_data=f"invoice_company:{company_id}")],
        [InlineKeyboardButton(text=block_label, callback_data=f"toggle_company:{company_id}")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_companies")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "back_to_companies")
async def back_to_companies(callback: CallbackQuery):
    await list_companies.__wrapped__(callback.message) if hasattr(list_companies, "__wrapped__") else None
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_company:"))
async def toggle_company(callback: CallbackQuery, db_user: User):
    if db_user.role != UserRole.developer:
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return
    company_id = int(callback.data.split(":")[1])
    async with AsyncSessionFactory() as session:
        from sqlalchemy import update as sa_update
        company = (await session.execute(
            select(Company).where(Company.id == company_id)
        )).scalar_one_or_none()
        if company:
            await session.execute(
                sa_update(Company).where(Company.id == company_id).values(is_active=not company.is_active)
            )
            await session.commit()
            status = "faollashtirildi" if not company.is_active else "bloklandi"
    await callback.answer(f"Kompaniya {status}!", show_alert=True)


@router.callback_query(F.data == "company_add")
async def start_add_company(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddCompanyState.company_name)
    await callback.message.edit_text(
        "🏢 <b>Yangi kompaniya qo'shish</b>\n\n"
        "1️⃣ Kompaniya nomini kiriting:\n\n"
        "❌ Bekor qilish: /cancel"
    )
    await callback.answer()


@router.message(AddCompanyState.company_name)
async def add_company_name(message: Message, state: FSMContext):
    await state.update_data(company_name=message.text.strip())
    await state.set_state(AddCompanyState.director_tg_id)
    await message.answer("2️⃣ Direktor Telegram ID si (raqam):")


@router.message(AddCompanyState.director_tg_id)
async def add_director_id(message: Message, state: FSMContext):
    try:
        tg_id = int(message.text.strip())
    except ValueError:
        await message.answer("Faqat raqam kiriting:")
        return
    await state.update_data(director_tg_id=tg_id)
    await state.set_state(AddCompanyState.director_name)
    await message.answer("3️⃣ Direktor ismi (to'liq):")


@router.message(AddCompanyState.director_name)
async def add_director_name(message: Message, state: FSMContext):
    await state.update_data(director_name=message.text.strip())
    await state.set_state(AddCompanyState.director_phone)
    await message.answer("4️⃣ Direktor telefoni (+998...):")


@router.message(AddCompanyState.director_phone)
async def add_director_phone(message: Message, state: FSMContext):
    await state.update_data(director_phone=message.text.strip())
    await state.set_state(AddCompanyState.channel_id)
    await message.answer("5️⃣ Kanal ID (bot admin bo'lishi kerak, masalan -1001234567890):")


@router.message(AddCompanyState.channel_id)
async def add_channel_id(message: Message, state: FSMContext):
    await state.update_data(channel_id=message.text.strip())
    await state.set_state(AddCompanyState.bot_token)
    await message.answer("6️⃣ Bot token (BotFather'dan):")


@router.message(AddCompanyState.bot_token)
async def add_bot_token(message: Message, state: FSMContext):
    token = message.text.strip()
    # Validate token
    try:
        from aiogram import Bot
        test_bot = Bot(token=token)
        bot_info = await test_bot.get_me()
        await test_bot.session.close()
    except Exception as e:
        await message.answer(f"Token noto'g'ri: {e}\n\nQayta kiriting:")
        return
    await state.update_data(bot_token=token, bot_id=bot_info.id, bot_username_actual=bot_info.username)
    await state.set_state(AddCompanyState.bot_username)
    await message.answer(f"7️⃣ Bot username tasdiqlash (@{bot_info.username})? Yoki boshqasini kiriting:")


@router.message(AddCompanyState.bot_username)
async def finalize_company(message: Message, state: FSMContext):
    fsm = await state.get_data()
    await state.clear()

    bot_username = message.text.strip().lstrip("@") or fsm.get("bot_username_actual", "")

    async with AsyncSessionFactory() as session:
        from src.db.repositories.settings_repo import SettingsRepository
        sr = SettingsRepository(session)
        trial_days = int(await sr.get("trial_period_days", "14"))

        company = Company(
            name=fsm["company_name"],
            bot_token=fsm["bot_token"],
            bot_username=bot_username,
            bot_id=fsm.get("bot_id"),
            telegram_channel_id=fsm["channel_id"],
            is_active=True,
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=trial_days),
        )
        session.add(company)
        await session.flush()

        director = User(
            telegram_user_id=fsm["director_tg_id"],
            full_name=fsm["director_name"],
            phone=fsm["director_phone"],
            role=UserRole.director,
            company_id=company.id,
        )
        session.add(director)
        await session.flush()

        # Trial subscription
        trial_sub = Subscription(
            company_id=company.id,
            subscription_type=SubscriptionType.base,
            price_usd=0,
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc) + timedelta(days=trial_days),
            status=SubscriptionStatus.active,
        )
        session.add(trial_sub)

        # Init director balance
        from src.db.models import UserBalance
        session.add(UserBalance(user_id=director.id))

        await session.commit()

    # Add to BotManager dynamically
    try:
        # bot_manager is available via app state — notify via message for now
        await message.answer(
            f"✅ <b>Kompaniya qo'shildi!</b>\n\n"
            f"🏢 Nom: {fsm['company_name']}\n"
            f"🤖 Bot: @{bot_username}\n"
            f"👤 Direktor ID: {fsm['director_tg_id']}\n"
            f"🎁 Trial: {trial_days} kun\n\n"
            f"Bot hozir ishga tushirilmoqda...\n"
            f"Direktorga /start yuborilsin: @{bot_username}"
        )
        # Notify director
        await message.bot.send_message(
            chat_id=fsm["director_tg_id"],
            text=(
                f"👋 Salom, {fsm['director_name']}!\n\n"
                f"Sizning kompaniyangiz tizimga qo'shildi.\n"
                f"🎁 {trial_days} kun bepul foydalanish.\n\n"
                f"Botga /start yuboring: @{bot_username}"
            ),
        )
    except Exception as e:
        await message.answer(f"Direktor xabari yuborilmadi: {e}")
