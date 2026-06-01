from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Company, User, UserRole
from src.bot.keyboards.client import main_menu_kb
from locales.uz import t

router = Router()


@router.message(F.text == t("btn_contact"))
async def contact_info(
    message: Message,
    db_user: User,
    db_session: AsyncSession,
    company: Company | None,
):
    company_id = db_user.company_id or (company.id if company else None)
    if company_id is None:
        await message.answer("Hozircha agentlar mavjud emas", reply_markup=main_menu_kb())
        return

    agents = (
        await db_session.execute(
            select(User)
            .where(
                User.company_id == company_id,
                User.role == UserRole.agent,
                User.is_blocked == False,
            )
            .order_by(User.full_name.asc(), User.id.asc())
        )
    ).scalars().all()

    if not agents:
        await message.answer("Hozircha agentlar mavjud emas", reply_markup=main_menu_kb())
        return

    lines = ["📞 Aloqa", ""]
    for agent in agents:
        name = agent.full_name or agent.username or f"Agent {agent.id}"
        phone = agent.phone or "Telefon ko'rsatilmagan"
        lines.append(f"• {name}\n  Telefon: {phone}")

    await message.answer("\n\n".join(lines), reply_markup=main_menu_kb())


@router.message(F.text == t("btn_help"))
async def help_info(message: Message):
    await message.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "🔍 <b>Uy qidirish</b> — tuman, xonalar va narx bo'yicha filter\n"
        "⭐ <b>Saralangan</b> — saqlagan uylaringiz\n"
        "💬 <b>Konsultatsiya</b> — AI yordamchi bilan muloqot\n"
        "🔔 <b>Bildirishnomalar</b> — yangi uy chiqsa xabar olish\n"
        "📞 <b>Aloqa</b> — agentlar bilan bog'lanish\n\n"
        "Obuna bekor qilish: /unsubscribe\n"
        "Botni qayta ishga tushirish: /start",
        parse_mode="HTML",
    )
