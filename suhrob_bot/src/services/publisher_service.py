import structlog
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Company, FileType
from src.db.repositories.property_repo import PropertyRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.utils.message_entities import load_message_entities
from src.utils.formatters import format_channel_post

logger = structlog.get_logger(__name__)


def _channel_inline_kb(bot_username: str, property_id: int) -> InlineKeyboardMarkup:
    url = f"https://t.me/{bot_username}?start=property_{property_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Botda ko'rish va savol berish", url=url)
    ]])


async def _send_message_with_entities(
    bot: Bot,
    *,
    chat_id,
    text: str,
    entities_json: list[dict] | None,
    reply_markup=None,
):
    entities = load_message_entities(entities_json)
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            entities=entities,
            parse_mode=None,
            reply_markup=reply_markup,
        )
    except Exception as exc:
        logger.warning("channel_entities_send_failed", error=str(exc))
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
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
        if company.bot_username:
            reply_markup = _channel_inline_kb(company.bot_username, property_id)

        media_items = [m for m in prop.media if m.file_type in (FileType.photo, FileType.video)]
        custom_text = prop.custom_text

        try:
            if custom_text:
                entities = load_message_entities(prop.custom_text_entities_json)
                if media_items and len(custom_text) <= 1024:
                    try:
                        if len(media_items) > 1:
                            media_group = [
                                _input_media_item(media_items[0], caption=custom_text, entities=entities, parse_mode=None),
                                *[_input_media_item(m) for m in media_items[1:]],
                            ]
                            msgs = await self.bot.send_media_group(chat_id=channel_id, media=media_group)
                            post_id = str(msgs[0].message_id)
                            if reply_markup:
                                await self.bot.send_message(
                                    chat_id=channel_id,
                                    text="Batafsil ma'lumot va savol uchun:",
                                    reply_markup=reply_markup,
                                )
                        else:
                            msg = await _send_single_media(
                                self.bot,
                                chat_id=channel_id,
                                media=media_items[0],
                                caption=custom_text,
                                entities=entities,
                                parse_mode=None,
                                reply_markup=reply_markup,
                            )
                            post_id = str(msg.message_id)
                    except Exception as exc:
                        logger.warning("channel_media_caption_entities_failed", error=str(exc))
                        if len(media_items) > 1:
                            media_group = [
                                _input_media_item(media_items[0], caption=custom_text, parse_mode=None),
                                *[_input_media_item(m) for m in media_items[1:]],
                            ]
                            msgs = await self.bot.send_media_group(chat_id=channel_id, media=media_group)
                            post_id = str(msgs[0].message_id)
                            if reply_markup:
                                await self.bot.send_message(
                                    chat_id=channel_id,
                                    text="Batafsil ma'lumot va savol uchun:",
                                    reply_markup=reply_markup,
                                )
                        else:
                            msg = await _send_single_media(
                                self.bot,
                                chat_id=channel_id,
                                media=media_items[0],
                                caption=custom_text,
                                parse_mode=None,
                                reply_markup=reply_markup,
                            )
                            post_id = str(msg.message_id)
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

                if len(media_items) > 1:
                    # Send media group first (no inline_kb on media groups), then button separately
                    media_group = [
                        _input_media_item(media_items[0], caption=caption, parse_mode="HTML"),
                        *[_input_media_item(m) for m in media_items[1:]],
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
                elif len(media_items) == 1:
                    msg = await _send_single_media(
                        self.bot,
                        chat_id=channel_id,
                        media=media_items[0],
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
