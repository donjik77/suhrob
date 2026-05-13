import structlog
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards.channel import build_channel_property_kb
from src.db.models import Company, FileType
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.utils.property_media import MEDIA_GROUP_LIMIT
from src.bot.utils.message_entities import load_message_entities
from src.utils.formatters import format_channel_post

logger = structlog.get_logger(__name__)


async def _copy_source_text_message(bot: Bot, *, chat_id, prop, reply_markup=None) -> str:
    if not prop.custom_text_source_chat_id or not prop.custom_text_source_message_id:
        raise ValueError("Premium emoji uchun e'lon matnini qayta yuboring va obyektni saqlang.")

    copied = await bot.copy_message(
        chat_id=chat_id,
        from_chat_id=prop.custom_text_source_chat_id,
        message_id=prop.custom_text_source_message_id,
        reply_markup=reply_markup,
    )
    return str(copied.message_id)


async def _send_message_with_entities(
    bot: Bot,
    *,
    chat_id,
    text: str,
    entities_json: list[dict] | None,
    reply_markup=None,
):
    entities = load_message_entities(entities_json)
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        entities=entities,
        parse_mode=None,
        reply_markup=reply_markup,
    )


def _input_media_item(media, *, caption: str | None = None, entities=None, parse_mode=None):
    kwargs = {"media": media.file_id}
    if caption is not None:
        kwargs["caption"] = caption
        if entities:
            kwargs["caption_entities"] = entities
            kwargs["parse_mode"] = None
        else:
            kwargs["parse_mode"] = parse_mode
    if media.file_type == FileType.video:
        return InputMediaVideo(**kwargs)
    return InputMediaPhoto(**kwargs)


def _media_chunks(media_items: list):
    for index in range(0, len(media_items), MEDIA_GROUP_LIMIT):
        yield media_items[index:index + MEDIA_GROUP_LIMIT]


async def _send_single_media(bot: Bot, *, chat_id, media, caption=None, entities=None, parse_mode=None, reply_markup=None):
    caption_kwargs = {"caption": caption, "reply_markup": reply_markup}
    if entities:
        caption_kwargs["caption_entities"] = entities
        caption_kwargs["parse_mode"] = None
    else:
        caption_kwargs["parse_mode"] = parse_mode

    if media.file_type == FileType.video:
        return await bot.send_video(
            chat_id=chat_id,
            video=media.file_id,
            **caption_kwargs,
        )
    return await bot.send_photo(
        chat_id=chat_id,
        photo=media.file_id,
        **caption_kwargs,
    )


async def _send_media_items(
    bot: Bot,
    *,
    chat_id,
    media_items: list,
    caption: str | None = None,
    entities=None,
    parse_mode=None,
    reply_markup=None,
    button_text: str = "Batafsil ma'lumot va savol uchun:",
):
    if not media_items:
        return []

    if len(media_items) == 1:
        msg = await _send_single_media(
            bot,
            chat_id=chat_id,
            media=media_items[0],
            caption=caption,
            entities=entities,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return [msg]

    sent_messages = []
    first_chunk = True
    for chunk in _media_chunks(media_items):
        if len(chunk) == 1:
            msg = await _send_single_media(
                bot,
                chat_id=chat_id,
                media=chunk[0],
                caption=caption if first_chunk else None,
                entities=entities if first_chunk else None,
                parse_mode=parse_mode if first_chunk else None,
            )
            sent_messages.append(msg)
        else:
            media_group = [
                _input_media_item(
                    media,
                    caption=caption if first_chunk and index == 0 else None,
                    entities=entities if first_chunk and index == 0 else None,
                    parse_mode=parse_mode if first_chunk and index == 0 else None,
                )
                for index, media in enumerate(chunk)
            ]
            sent_messages.extend(await bot.send_media_group(chat_id=chat_id, media=media_group))
        first_chunk = False

    if reply_markup:
        await bot.send_message(
            chat_id=chat_id,
            text=button_text,
            reply_markup=reply_markup,
        )

    return sent_messages


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

        channel_id = company.telegram_channel_id

        # Inline button for deep link back to bot
        reply_markup = None
        if not property_id:
            logger.warning(
                "channel_property_button_missing_property_id",
                company_id=getattr(company, "id", None),
            )
        elif company.bot_username:
            reply_markup = build_channel_property_kb(company.bot_username, property_id)
        else:
            logger.error(
                "channel_property_button_missing_bot_username",
                company_id=getattr(company, "id", None),
                property_id=property_id,
            )

        media_items = [m for m in prop.media if m.file_type in (FileType.photo, FileType.video)]
        custom_text = prop.custom_text

        try:
            if custom_text:
                entities = load_message_entities(prop.custom_text_entities_json)
                if media_items and len(custom_text) <= 1024:
                    msgs = await _send_media_items(
                        self.bot,
                        chat_id=channel_id,
                        media_items=media_items,
                        caption=custom_text,
                        entities=entities,
                        parse_mode=None,
                        reply_markup=reply_markup,
                    )
                    post_id = str(msgs[0].message_id)
                else:
                    if media_items:
                        await _send_media_items(
                            self.bot,
                            chat_id=channel_id,
                            media_items=media_items,
                        )
                    if prop.custom_text_source_chat_id:
                        post_id = await _copy_source_text_message(
                            self.bot,
                            chat_id=channel_id,
                            prop=prop,
                            reply_markup=reply_markup,
                        )
                    else:
                        msg = await _send_message_with_entities(
                            self.bot,
                            chat_id=channel_id,
                            text=custom_text,
                            entities_json=prop.custom_text_entities_json,
                            reply_markup=reply_markup,
                        )
                        post_id = str(msg.message_id)

            else:
                settings_repo = SettingsRepository(self.session)
                rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
                caption = format_channel_post(prop, rate)

                if media_items:
                    msgs = await _send_media_items(
                        self.bot,
                        chat_id=channel_id,
                        media_items=media_items,
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=reply_markup,
                        button_text="👆 Batafsil ma'lumot va savol uchun:",
                    )
                    post_id = str(msgs[0].message_id)
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
