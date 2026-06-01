from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from src.bot.keyboards.styles import BTN_SUCCESS

CHANNEL_WELCOME_TEXT = (
    "👋 Assalomu alaykum!\n\n"
    "Suhrob HOUSE kanaliga xush kelibsiz.\n\n"
    "Uy qidiryapsizmi?\n"
    "Bot orqali qidirish ancha qulay:\n\n"
    "✅ byudjet bo'yicha saralash\n"
    "✅ hudud bo'yicha qidirish\n"
    "✅ uy haqida savol berish\n"
    "✅ agent bilan tez bog'lanish\n\n"
    "👇 Boshlash uchun tugmani bosing:"
)


def build_channel_welcome_kb(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🤖 Bot orqali qidirish",
                url=f"https://t.me/{bot_username}?start=channel_welcome",
                style=BTN_SUCCESS,
            )
        ]]
    )
