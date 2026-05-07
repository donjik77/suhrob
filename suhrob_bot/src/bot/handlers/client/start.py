from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import User, UserRole
from src.bot.keyboards.client import main_menu_kb
from locales.uz import t

router = Router()


@router.message(F.text == "📞 Aloqa")
async def contact_info(message: Message, db_user: User):
    await message.answer(
        "📞 Aloqa:\n\nSuhrob HOUSE bilan bog'lanish uchun:\nTelegram: @suhrob_house",
        reply_markup=main_menu_kb(),
    )
