from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.db.models import User, UserRole
from src.db.session import AsyncSessionFactory
from src.db.repositories.user_repo import UserRepository
from src.bot.filters.role import RoleFilter
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.director, UserRole.developer))


@router.message(F.text == "🔵 👥 Agentlar boshqaruvi")
async def list_agents(message: Message, db_user: User):
    if db_user.company_id is None:
        await message.answer("Kompaniya topilmadi.")
        return

    async with AsyncSessionFactory() as session:
        repo = UserRepository(session)
        agents = await repo.get_company_users(db_user.company_id)

    if not agents:
        await message.answer("Kompaniyada agentlar yo'q.")
        return

    builder = InlineKeyboardBuilder()
    lines = ["👥 Kompaniya agentlari:\n"]
    for agent in agents:
        if agent.role in (UserRole.agent, UserRole.director):
            name = agent.full_name or agent.username or str(agent.telegram_user_id)
            role_label = "direktor" if agent.role == UserRole.director else "agent"
            lines.append(f"• {name} ({role_label})")
            builder.button(
                text=f"⚙️ {name}",
                callback_data=f"agent_manage:{agent.id}",
            )

    builder.adjust(1)
    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("agent_manage:"))
async def manage_agent(callback: CallbackQuery, db_user: User):
    agent_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.id == agent_id)
        )
        agent = result.scalar_one_or_none()

    if not agent:
        await callback.answer("Agent topilmadi", show_alert=True)
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
async def toggle_agent_block(callback: CallbackQuery):
    parts = callback.data.split(":")
    agent_id = int(parts[1])
    blocked = parts[2] == "1"

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update
        await session.execute(
            update(User).where(User.id == agent_id).values(is_blocked=blocked)
        )
        await session.commit()

    status = "bloklandi" if blocked else "blokdan chiqarildi"
    await callback.answer(f"Agent {status}", show_alert=True)
    await callback.message.delete()
