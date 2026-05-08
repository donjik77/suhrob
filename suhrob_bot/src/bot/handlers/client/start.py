from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import User, UserRole
from src.bot.keyboards.client import main_menu_kb
from locales.uz import t

router = Router()


@router.message(F.text == "🔵 📞 Aloqa")
async def contact_info(message: Message, db_user: User):
    await message.answer(
        "📞 Aloqa:\n\nSuhrob HOUSE bilan bog'lanish uchun:\nTelegram: @suhrob_house",
        reply_markup=main_menu_kb(),
    )


@router.message(F.text == "🔵 ℹ️ Yordam")
async def help_info(message: Message):
    await message.answer(
        "ℹ️ <b>Yordam</b>\n\n"
        "🔵 🔍 <b>Uy qidirish</b> — tuman, xonalar va narx bo'yicha filter\n"
        "🟣 ⭐ <b>Saralangan</b> — saqlagan uylaringiz\n"
        "🟢 💬 <b>Konsultatsiya</b> — AI yordamchi bilan muloqot\n"
        "🟡 🔔 <b>Bildirishnomalar</b> — yangi uy chiqsa xabar olish\n"
        "🔵 📞 <b>Aloqa</b> — agentlar bilan bog'lanish\n\n"
        "Obuna bekor qilish: /unsubscribe\n"
        "Botni qayta ishga tushirish: /start",
        parse_mode="HTML",
    )
