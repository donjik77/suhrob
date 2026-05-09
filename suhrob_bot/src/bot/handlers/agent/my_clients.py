"""Agent CRM — view assigned leads with qualification scores."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import User, UserRole, LeadAssignment, LeadStatus, ClientProfile
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


async def get_lead_for_agent(
    lead_id: int,
    agent: User,
    session: AsyncSession,
) -> LeadAssignment | None:
    result = await session.execute(
        select(LeadAssignment)
        .where(
            LeadAssignment.id == lead_id,
            LeadAssignment.agent_user_id == agent.id,
        )
        .options(
            selectinload(LeadAssignment.client),
            selectinload(LeadAssignment.agent),
            selectinload(LeadAssignment.property),
        )
    )
    return result.scalar_one_or_none()


async def get_lead_for_director(
    lead_id: int,
    director: User,
    session: AsyncSession,
) -> LeadAssignment | None:
    result = await session.execute(
        select(LeadAssignment)
        .join(User, User.id == LeadAssignment.agent_user_id)
        .where(
            LeadAssignment.id == lead_id,
            User.company_id == director.company_id,
            User.role == UserRole.agent,
        )
        .options(
            selectinload(LeadAssignment.client),
            selectinload(LeadAssignment.agent),
            selectinload(LeadAssignment.property),
        )
    )
    return result.scalar_one_or_none()


STATUS_LABELS = {
    LeadStatus.new: "Yangi",
    LeadStatus.contacted: "📞 Bog'langan",
    LeadStatus.showing_scheduled: "🏠 Ko'rsatuv",
    LeadStatus.negotiation: "💼 Muzokarada",
    LeadStatus.closed_won: "✅ Sotilgan",
    LeadStatus.closed_lost: "❌ Yo'qotilgan",
}


@router.message(F.text == "🔥 Mening mijozlarim")
async def my_clients_menu(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        counts = {}
        for status in LeadStatus:
            result = await session.execute(
                select(LeadAssignment).where(
                    LeadAssignment.agent_user_id == db_user.id,
                    LeadAssignment.status == status,
                )
            )
            counts[status] = len(result.scalars().all())

    lines = ["👥 <b>Mening mijozlarim</b>\n"]
    for status, label in STATUS_LABELS.items():
        lines.append(f"{label}: {counts.get(status, 0)}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{label} ({counts.get(s, 0)})", callback_data=f"leads_by_status:{s.value}")]
        for s, label in STATUS_LABELS.items()
    ])
    await message.answer("\n".join(lines), reply_markup=kb)


@router.message(F.text == "🔥 Barcha mijozlar")
async def all_clients_menu(message: Message, db_user: User):
    if db_user.role not in (UserRole.director, UserRole.developer):
        await message.answer("❌ Ruxsat yo'q")
        return
    if db_user.company_id is None:
        await message.answer("Kompaniya topilmadi.")
        return

    async with AsyncSessionFactory() as session:
        counts = {}
        for status in LeadStatus:
            result = await session.execute(
                select(LeadAssignment)
                .join(User, User.id == LeadAssignment.agent_user_id)
                .where(
                    User.company_id == db_user.company_id,
                    User.role == UserRole.agent,
                    LeadAssignment.status == status,
                )
            )
            counts[status] = len(result.scalars().all())

    lines = ["👥 <b>Barcha mijozlar</b>\n"]
    for status, label in STATUS_LABELS.items():
        lines.append(f"{label}: {counts.get(status, 0)}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{label} ({counts.get(s, 0)})", callback_data=f"director_leads_by_status:{s.value}")]
        for s, label in STATUS_LABELS.items()
    ])
    await message.answer("\n".join(lines), reply_markup=kb)


@router.callback_query(F.data.startswith("leads_by_status:"))
async def leads_by_status(callback: CallbackQuery, db_user: User):
    status_val = callback.data.split(":")[1]
    status = LeadStatus(status_val)

    async with AsyncSessionFactory() as session:
        rows = (
            await session.execute(
                select(LeadAssignment)
                .where(
                    LeadAssignment.agent_user_id == db_user.id,
                    LeadAssignment.status == status,
                )
                .options(selectinload(LeadAssignment.client))
                .order_by(LeadAssignment.created_at.desc())
            )
        ).scalars().all()

        if not rows:
            await callback.answer("Bu kategoriyada mijozlar yo'q.", show_alert=True)
            return

        lines = [f"👥 <b>{STATUS_LABELS[status]}</b>\n"]
        buttons = []
        for lead in rows:
            client = lead.client
            profile = (
                await session.execute(
                    select(ClientProfile).where(ClientProfile.user_id == client.id)
                )
            ).scalar_one_or_none()
            score = profile.qualification_score if profile else 0
            score_icon = "🔥" if score >= 70 else ("⭐" if score >= 40 else "⚪")
            budget = ""
            if profile and profile.budget_max_usd:
                budget = f" · ${int(profile.budget_max_usd):,}"
            name = client.full_name or client.username or f"ID:{client.telegram_user_id}"
            lines.append(f"{score_icon} {name} — {score}/100{budget}")
            buttons.append([
                InlineKeyboardButton(
                    text=f"👤 {name}",
                    callback_data=f"lead_detail:{lead.id}",
                )
            ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("director_leads_by_status:"))
async def director_leads_by_status(callback: CallbackQuery, db_user: User):
    if db_user.role not in (UserRole.director, UserRole.developer):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    status_val = callback.data.split(":")[1]
    status = LeadStatus(status_val)

    async with AsyncSessionFactory() as session:
        rows = (
            await session.execute(
                select(LeadAssignment)
                .join(User, User.id == LeadAssignment.agent_user_id)
                .where(
                    User.company_id == db_user.company_id,
                    User.role == UserRole.agent,
                    LeadAssignment.status == status,
                )
                .options(
                    selectinload(LeadAssignment.client),
                    selectinload(LeadAssignment.agent),
                )
                .order_by(LeadAssignment.created_at.desc())
            )
        ).scalars().all()

        if not rows:
            await callback.answer("Bu kategoriyada mijozlar yo'q.", show_alert=True)
            return

        lines = [f"👥 <b>{STATUS_LABELS[status]}</b>\n"]
        buttons = []
        for lead in rows:
            client = lead.client
            agent = lead.agent
            profile = (
                await session.execute(
                    select(ClientProfile).where(ClientProfile.user_id == client.id)
                )
            ).scalar_one_or_none()
            score = profile.qualification_score if profile else 0
            score_icon = "🔥" if score >= 70 else ("⭐" if score >= 40 else "⚪")
            client_name = client.full_name or client.username or f"ID:{client.telegram_user_id}"
            agent_name = agent.full_name or agent.username or "—"
            lines.append(f"{score_icon} {client_name} — {score}/100 | Agent: {agent_name}")
            buttons.append([InlineKeyboardButton(text=f"👤 {client_name}", callback_data=f"director_lead_detail:{lead.id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("lead_detail:"))
async def lead_detail(callback: CallbackQuery, db_user: User):
    lead_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        lead = await get_lead_for_agent(lead_id, db_user, session)
        if not lead:
            await callback.answer("❌ Bunday mijoz topilmadi yoki sizniki emas", show_alert=True)
            return

        client = lead.client
        profile = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == client.id)
            )
        ).scalar_one_or_none()

    score = profile.qualification_score if profile else 0
    budget = (
        f"${int(profile.budget_min_usd or 0):,} – ${int(profile.budget_max_usd or 0):,}"
        if profile else "—"
    )
    districts = ", ".join(profile.preferred_districts or []) if profile else "—"
    name = client.full_name or client.username or f"ID:{client.telegram_user_id}"
    username_str = f"@{client.username}" if client.username else "—"
    notes = (profile.notes or "—") if profile else "—"

    text = (
        f"👤 <b>{name}</b> ({username_str})\n"
        f"⭐ Sifat: <b>{score}/100</b>\n\n"
        f"💰 Byudjet: {budget}\n"
        f"📍 Tuman: {districts}\n"
        f"💳 To'lov: {profile.payment_method or '—' if profile else '—'}\n"
        f"⏱ Muddat: {profile.purchase_timeline or '—' if profile else '—'}\n\n"
        f"📝 AI xulosasi:\n{notes}"
    )

    status_buttons = [
        InlineKeyboardButton(
            text=label, callback_data=f"lead_update:{lead.id}:{status.value}"
        )
        for status, label in STATUS_LABELS.items()
        if status != lead.status
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[status_buttons[i:i+2] for i in range(0, len(status_buttons), 2)]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("director_lead_detail:"))
async def director_lead_detail(callback: CallbackQuery, db_user: User):
    lead_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        lead = await get_lead_for_director(lead_id, db_user, session)
        if not lead:
            await callback.answer("❌ Bunday mijoz topilmadi yoki kompaniyangizdan emas", show_alert=True)
            return

        client = lead.client
        profile = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == client.id)
            )
        ).scalar_one_or_none()

    score = profile.qualification_score if profile else 0
    budget = (
        f"${int(profile.budget_min_usd or 0):,} – ${int(profile.budget_max_usd or 0):,}"
        if profile else "—"
    )
    districts = ", ".join(profile.preferred_districts or []) if profile else "—"
    name = client.full_name or client.username or f"ID:{client.telegram_user_id}"
    username_str = f"@{client.username}" if client.username else "—"
    agent_name = lead.agent.full_name or lead.agent.username or "—"
    prop_title = lead.property.title if lead.property else "—"
    notes = (profile.notes or "—") if profile else "—"

    text = (
        f"👤 <b>{name}</b> ({username_str})\n"
        f"👔 Agent: <b>{agent_name}</b>\n"
        f"🏠 Obyekt: {prop_title}\n"
        f"⭐ Sifat: <b>{score}/100</b>\n\n"
        f"💰 Byudjet: {budget}\n"
        f"📍 Tuman: {districts}\n"
        f"💳 To'lov: {profile.payment_method or '—' if profile else '—'}\n"
        f"⏱ Muddat: {profile.purchase_timeline or '—' if profile else '—'}\n\n"
        f"📝 AI xulosasi:\n{notes}"
    )

    status_buttons = [
        InlineKeyboardButton(
            text=label, callback_data=f"director_lead_update:{lead.id}:{status.value}"
        )
        for status, label in STATUS_LABELS.items()
        if status != lead.status
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[status_buttons[i:i+2] for i in range(0, len(status_buttons), 2)]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("lead_update:"))
async def update_lead_status(callback: CallbackQuery, db_user: User):
    parts = callback.data.split(":")
    lead_id = int(parts[1])
    new_status = LeadStatus(parts[2])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update as sa_update
        existing = await get_lead_for_agent(lead_id, db_user, session)
        if not existing:
            await callback.answer("❌ Bunday mijoz topilmadi yoki sizniki emas", show_alert=True)
            return
        await session.execute(
            sa_update(LeadAssignment)
            .where(
                LeadAssignment.id == lead_id,
                LeadAssignment.agent_user_id == db_user.id,
            )
            .values(status=new_status)
        )
        await session.commit()

    await callback.answer(f"Status o'zgartirildi: {STATUS_LABELS[new_status]}", show_alert=True)


@router.callback_query(F.data.startswith("director_lead_update:"))
async def director_update_lead_status(callback: CallbackQuery, db_user: User):
    if db_user.role not in (UserRole.director, UserRole.developer):
        await callback.answer("❌ Ruxsat yo'q", show_alert=True)
        return

    parts = callback.data.split(":")
    lead_id = int(parts[1])
    new_status = LeadStatus(parts[2])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update as sa_update
        existing = await get_lead_for_director(lead_id, db_user, session)
        if not existing:
            await callback.answer("❌ Bunday mijoz topilmadi yoki kompaniyangizdan emas", show_alert=True)
            return
        await session.execute(
            sa_update(LeadAssignment)
            .where(LeadAssignment.id == lead_id)
            .values(status=new_status)
        )
        await session.commit()

    await callback.answer(f"Status o'zgartirildi: {STATUS_LABELS[new_status]}", show_alert=True)
