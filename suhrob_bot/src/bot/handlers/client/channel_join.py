from aiogram import Router
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton

from src.db.models import Company

router = Router()


@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_channel_join(event: ChatMemberUpdated, company: Company | None = None):
    user = event.new_chat_member.user
    if user.is_bot:
        return

    if company and str(event.chat.id) != str(company.telegram_channel_id):
        return

    bot_username = (company.bot_username if company else None) or "samarqand_uylaribot"

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🏠 Uy qidirish",
            url=f"https://t.me/{bot_username}",
        )
    ]])

    default_name = "Do'st"
    try:
        await event.bot.send_message(
            user.id,
            f"👋 Salom, <b>{user.full_name or default_name}</b>!\n\n"
            f"<b>Samarqand Uylari</b> kanaliga xush kelibsiz! 🏠\n\n"
            f"Botimizda siz:\n"
            f"• Ko'chmas mulk qidira olasiz\n"
            f"• AI-konsultant bilan gaplasha olasiz\n"
            f"• Yangi variantlarga obuna bo'la olasiz\n\n"
            f"Boshlash uchun quyidagi tugmani bosing 👇",
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        pass
