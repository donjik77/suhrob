from aiogram import Bot
from aiogram.types import InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.models import Company, PropertyStatus
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.utils.formatters import format_channel_post


def _channel_inline_kb(bot_username: str, property_id: int) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=property_{property_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🟢 Botda ko'rish va savol berish", url=url)
    ]])


class PublisherService:
    def __init__(self, session: AsyncSession, bot: Bot):
        self.session = session
        self.bot = bot

    async def publish(self, property_id: int) -> tuple[bool, str]:
        repo = PropertyRepository(self.session)
        prop = await repo.get_by_id(property_id)

        if not prop:
            return False, "Uy topilmadi."

        company = await self.session.get(Company, prop.company_id)
        if not company or not company.telegram_channel_id:
            return False, "Kanal ID topilmadi. Sozlamalarda kanal ID kiriting."

        settings_repo = SettingsRepository(self.session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

        caption = format_channel_post(prop, rate)
        channel_id = company.telegram_channel_id

        # Inline button for deep link back to bot
        reply_markup = None
        if company.bot_username:
            reply_markup = _channel_inline_kb(company.bot_username, property_id)

        photos = [m for m in prop.media if m.file_type.value == "photo"]

        try:
            if len(photos) > 1:
                # Send media group first (no inline_kb on media groups), then button separately
                media_group = [
                    InputMediaPhoto(media=photos[0].file_id, caption=caption, parse_mode="HTML"),
                    *[InputMediaPhoto(media=p.file_id) for p in photos[1:]],
                ]
                msgs = await self.bot.send_media_group(chat_id=channel_id, media=media_group)
                post_id = str(msgs[0].message_id)
                # Send button as separate message
                if reply_markup:
                    await self.bot.send_message(
                        chat_id=channel_id,
                        text="👆 Batafsil ma'lumot va savol uchun:",
                        reply_markup=reply_markup,
                    )
            elif len(photos) == 1:
                msg = await self.bot.send_photo(
                    chat_id=channel_id,
                    photo=photos[0].file_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                post_id = str(msg.message_id)
            else:
                msg = await self.bot.send_message(
                    chat_id=channel_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                post_id = str(msg.message_id)

            await repo.update_telegram_post_id(property_id, post_id)
            return True, f"✅ Kanal {channel_id}ga muvaffaqiyatli e'lon qilindi!"

        except Exception as e:
            return False, str(e)
