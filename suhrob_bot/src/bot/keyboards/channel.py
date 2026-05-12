from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.keyboards.styles import BTN_SUCCESS


def build_channel_property_kb(
    bot_username: str,
    property_id: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Bot orqali so'rash",
                    url=f"https://t.me/{bot_username}?start=property_{property_id}",
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )
