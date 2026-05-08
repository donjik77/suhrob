import re as _re
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select as sa_select, func, distinct

from src.db.models import User, UserRole, Property, PropertyStatus
from src.db.session import AsyncSessionFactory
from src.db.repositories.user_repo import UserRepository
from src.bot.filters.role import RoleFilter
from src.bot.handlers.director.company_scope import resolve_actor_company_id
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.director, UserRole.developer))


@router.message(F.text == "🔵 👥 Agentlar boshqaruvi")
async def list_agents(message: Message, db_user: User):
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await message.answer("Kompaniya topilmadi.")
        return

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        agents = await repo.get_company_users_by_role(company_id, UserRole.agent)

    builder = InlineKeyboardBuilder()
    lines = ["👥 Kompaniya agentlari:\n"]
    if not agents:
        lines.append("Hozircha agentlar yo'q.")
    else:
        for agent in agents:
            name = agent.full_name or agent.username or str(agent.telegram_user_id)
            lines.append(f"• {name} (agent)")
            builder.button(
                text=f"⚙️ {name}",
                callback_data=f"agent_manage:{agent.id}",
            )
    builder.button(text="➕ Yangi agent qo'shish", callback_data="add_agent")

    builder.adjust(1)
    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("agent_manage:"))
async def manage_agent(callback: CallbackQuery, db_user: User):
    agent_id = int(callback.data.split(":")[1])
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await callback.answer("Kompaniya topilmadi.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(
                User.id == agent_id,
                User.company_id == company_id,
                User.role == UserRole.agent,
            )
        )
        agent = result.scalar_one_or_none()

    if not agent:
        await callback.answer("Agent topilmadi yoki sizning kompaniyangizdan emas", show_alert=True)
        return

    name = agent.full_name or agent.username or str(agent.telegram_user_id)
    builder = InlineKeyboardBuilder()
    if not agent.is_blocked:
        builder.button(text="🚫 Bloklash", callback_data=f"agent_block:{agent_id}:1")
    else:
        builder.button(text="✅ Blokdan chiqarish", callback_data=f"agent_block:{agent_id}:0")
    builder.adjust(1)

    await callback.message.answer(
        f"Agent: {name}\nStatus: {'🚫 Bloklangan' if agent.is_blocked else '✅ Faol'}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("agent_block:"))
async def toggle_agent_block(callback: CallbackQuery, db_user: User):
    parts = callback.data.split(":")
    agent_id = int(parts[1])
    blocked = parts[2] == "1"
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await callback.answer("Kompaniya topilmadi.", show_alert=True)
        return

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select, update
        target = (await session.execute(
            select(User).where(
                User.id == agent_id,
                User.company_id == company_id,
                User.role == UserRole.agent,
            )
        )).scalar_one_or_none()

        if not target:
            await callback.answer("❌ Agent topilmadi yoki sizning kompaniyangizdan emas", show_alert=True)
            return

        await session.execute(
            update(User)
            .where(
                User.id == agent_id,
                User.company_id == company_id,
                User.role == UserRole.agent,
            )
            .values(is_blocked=blocked)
        )
        await session.commit()

    status = "bloklandi" if blocked else "blokdan chiqarildi"
    await callback.answer(f"Agent {status}", show_alert=True)
    await callback.message.delete()


# ─── Add Agent FSM ────────────────────────────────────────────────────────────

class AddAgentStates(StatesGroup):
    waiting_full_name = State()
    waiting_phone = State()
    waiting_telegram = State()


@router.callback_query(F.data == "add_agent")
async def start_add_agent(callback: CallbackQuery, state: FSMContext, db_user: User):
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await callback.answer("Kompaniya topilmadi.", show_alert=True)
        return
    await callback.message.answer(
        "➕ <b>Yangi agent qo'shish</b>\n\n"
        "1/3. Agentning to'liq ism va familiyasini kiriting:",
        parse_mode='HTML',
    )
    await state.set_state(AddAgentStates.waiting_full_name)
    await callback.answer()


@router.message(StateFilter(AddAgentStates.waiting_full_name))
async def add_agent_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3 or len(name) > 100:
        await message.answer("❌ Ism noto'g'ri. Iltimos, qaytadan kiriting:")
        return
    await state.update_data(full_name=name)
    await message.answer("2/3. Telefon raqamini kiriting (format: +998XXXXXXXXX):")
    await state.set_state(AddAgentStates.waiting_phone)


@router.message(StateFilter(AddAgentStates.waiting_phone))
async def add_agent_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not _re.match(r'^\+998\d{9}$', phone):
        await message.answer("❌ Telefon noto'g'ri. Format: +998901234567\nQaytadan kiriting:")
        return
    await state.update_data(phone=phone)
    await message.answer(
        "3/3. Telegram username (@username) yoki Telegram ID:\n\n"
        "💡 Agent o'z botida @userinfobot ga /start yuborsin"
    )
    await state.set_state(AddAgentStates.waiting_telegram)


@router.message(StateFilter(AddAgentStates.waiting_telegram))
async def add_agent_telegram(message: Message, state: FSMContext, db_user: User, bot):
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await message.answer("Kompaniya topilmadi.")
        await state.clear()
        return

    text = message.text.strip()
    telegram_user_id = None
    username = None

    if text.startswith('@'):
        username = text[1:]
    elif text.lstrip('-').isdigit():
        telegram_user_id = int(text)
    else:
        await message.answer("❌ Format noto'g'ri. @username yoki raqam kiriting:")
        return

    data = await state.get_data()

    async with AsyncSessionFactory() as session:
        if telegram_user_id:
            existing = await session.execute(
                sa_select(User).where(
                    User.telegram_user_id == telegram_user_id,
                    User.company_id == company_id,
                )
            )
            if existing.scalar_one_or_none():
                await message.answer("❌ Bu Telegram ID kompaniyangizda allaqachon bor")
                await state.clear()
                return
        elif username:
            existing_pending = await session.execute(
                sa_select(User).where(
                    User.telegram_user_id == 0,
                    func.lower(User.username) == username.lower(),
                    User.company_id == company_id,
                    User.role == UserRole.agent,
                )
            )
            if existing_pending.scalar_one_or_none():
                await message.answer("❌ Bu username bo'yicha agent allaqachon kutilmoqda")
                await state.clear()
                return

        new_agent = User(
            telegram_user_id=telegram_user_id or 0,
            username=username,
            full_name=data['full_name'],
            phone=data['phone'],
            role=UserRole.agent,
            company_id=company_id,
        )
        session.add(new_agent)
        await session.commit()
        await session.refresh(new_agent)
        new_agent_id = new_agent.id

    sent = False
    if telegram_user_id:
        try:
            invite_msg = (
                f"👋 Salom, <b>{data['full_name']}</b>!\n\n"
                f"Sizni kompaniyaga agent sifatida qo'shdilar.\n\n"
                f"Botda ishlash uchun /start yuboring."
            )
            await bot.send_message(telegram_user_id, invite_msg, parse_mode='HTML')
            sent = True
        except Exception:
            pass

    summary = (
        f"✅ <b>Agent yaratildi!</b>\n\n"
        f"📛 Ism: {data['full_name']}\n"
        f"📞 Telefon: {data['phone']}\n"
        f"🆔 ID: {new_agent_id}\n"
    )
    if sent:
        summary += "\n📨 Taklifnoma yuborildi"
    elif username:
        summary += f"\n💡 Iltiros, @{username} ga shu botning linkini yuboring"
    else:
        summary += "\n💡 Agent botga /start yuboradi va avtomatik avtorizatsiya bo'ladi"

    await message.answer(summary, parse_mode='HTML')
    await state.clear()


@router.message(F.text.contains("reytingi"))
async def agents_rating(message: Message, db_user: User):
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await message.answer("Kompaniya topilmadi.")
        return

    period_start = datetime.now(timezone.utc) - timedelta(days=30)

    async with AsyncSessionFactory() as session:
        stmt = (
            sa_select(
                User.id,
                User.full_name,
                func.count(distinct(Property.id)).filter(
                    Property.created_at >= period_start
                ).label('new_properties'),
                func.coalesce(func.sum(Property.views_count), 0).label('views'),
                func.coalesce(func.sum(Property.contacts_count), 0).label('contacts'),
                func.count(distinct(Property.id)).filter(
                    Property.status == PropertyStatus.sold
                ).label('sold'),
            )
            .outerjoin(Property, Property.agent_id == User.id)
            .where(
                User.role == UserRole.agent,
                User.company_id == company_id,
                User.is_blocked == False,
            )
            .group_by(User.id, User.full_name)
        )
        result = await session.execute(stmt)
        rows = result.all()

    ranked = []
    for row in rows:
        views = int(row.views or 0)
        contacts = int(row.contacts or 0)
        sold = int(row.sold or 0)
        new_props = int(row.new_properties or 0)
        conversion = (sold / views * 100) if views > 0 else 0
        contact_rate = (contacts / views * 100) if views > 0 else 0
        score = min(100, int(conversion * 5 + contact_rate * 2 + new_props * 3))
        ranked.append((row.full_name, new_props, views, contacts, sold, score))

    ranked.sort(key=lambda r: r[5], reverse=True)
    medals = ['🥇', '🥈', '🥉'] + ['🏅'] * 100
    text = "<b>👥 Agentlar reytingi</b> (oxirgi 30 kun)\n\n"

    for i, (name, new_props, views, contacts, sold, score) in enumerate(ranked):
        text += (
            f"{medals[i]} <b>{name}</b>\n"
            f"   🏠 Yangi: {new_props}  👁 Ko'rishlar: {views}\n"
            f"   📞 Bog'lanishlar: {contacts}  ✅ Sotilgan: {sold}\n"
            f"   ⭐ Aktivlik: {score}/100\n\n"
        )

    if not ranked:
        text += "Hozircha agentlar yo'q"

    await message.answer(text, parse_mode='HTML')
