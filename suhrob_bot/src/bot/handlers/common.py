from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.db.models import User, UserRole
from src.bot.keyboards.client import main_menu_kb
from src.bot.keyboards.agent import agent_menu_kb
from locales.uz import t

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User):
    name = message.from_user.full_name or message.from_user.username or "Foydalanuvchi"

    if db_user.role == UserRole.client:
        await message.answer(
            t("welcome", name=name),
            reply_markup=main_menu_kb(),
        )
    else:
        await message.answer(
            t("agent_menu_welcome", name=name),
            reply_markup=agent_menu_kb(db_user.role),
        )
