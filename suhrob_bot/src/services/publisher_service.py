from aiogram import Bot
from aiogram.types import InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.models import Company, PropertyStatus
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.utils.formatters import format_channel_post


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

        photos = [m for m in prop.media if m.file_type.value == "photo"]
        videos = [m for m in prop.media if m.file_type.value == "video"]

        try:
            if len(photos) > 1:
                media_group = [
                    InputMediaPhoto(media=photos[0].file_id, caption=caption),
                    *[InputMediaPhoto(media=p.file_id) for p in photos[1:]],
                ]
                msgs = await self.bot.send_media_group(chat_id=channel_id, media=media_group)
                post_id = str(msgs[0].message_id)
            elif len(photos) == 1:
                msg = await self.bot.send_photo(
                    chat_id=channel_id,
                    photo=photos[0].file_id,
                    caption=caption,
                )
                post_id = str(msg.message_id)
            else:
                msg = await self.bot.send_message(chat_id=channel_id, text=caption)
                post_id = str(msg.message_id)

            await repo.update_telegram_post_id(property_id, post_id)
            return True, f"✅ Kanal {channel_id}ga muvaffaqiyatli e'lon qilindi!"

        except Exception as e:
            return False, str(e)
