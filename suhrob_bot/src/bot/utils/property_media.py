from collections.abc import Iterable

from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo, Message

from src.db.models import FileType
from src.bot.utils.message_entities import load_message_entities


MEDIA_GROUP_LIMIT = 10
MEDIA_BUTTON_TEXT = "👆"


def _file_type_value(media) -> str:
    file_type = media.get("file_type", "") if isinstance(media, dict) else getattr(media, "file_type", "")
    return getattr(file_type, "value", file_type)


def _file_id(media) -> str:
    return media["file_id"] if isinstance(media, dict) else media.file_id


def _is_supported_media(media) -> bool:
    return _file_type_value(media) in (FileType.photo.value, FileType.video.value)


def _is_video(media) -> bool:
    return _file_type_value(media) == FileType.video.value


def property_media_items(media_items: Iterable) -> list:
    """Return only supported property media in display order."""
    return [media for media in (media_items or []) if _is_supported_media(media)]


def _entity_kwargs(entities, parse_mode: str | None, *, caption: bool) -> dict:
    if entities:
        return {
            "caption_entities" if caption else "entities": entities,
            "parse_mode": None,
        }
    return {"parse_mode": parse_mode}


def _input_media(
    media,
    *,
    caption: str | None = None,
    parse_mode: str | None = "HTML",
    caption_entities=None,
):
    kwargs = {"media": _file_id(media)}
    if caption is not None:
        kwargs["caption"] = caption
        kwargs.update(_entity_kwargs(caption_entities, parse_mode, caption=True))

    if _is_video(media):
        return InputMediaVideo(**kwargs)
    return InputMediaPhoto(**kwargs)


def _media_chunks(media_items: list) -> Iterable[list]:
    for index in range(0, len(media_items), MEDIA_GROUP_LIMIT):
        yield media_items[index:index + MEDIA_GROUP_LIMIT]


async def answer_property_media_card(
    message: Message,
    *,
    media_items: Iterable,
    caption: str,
    reply_markup=None,
    parse_mode: str | None = "HTML",
    caption_entities_json: list[dict] | None = None,
) -> None:
    """Send a property card and all attached photo/video media to a chat."""
    items = property_media_items(media_items)
    caption_entities = load_message_entities(caption_entities_json)

    if not items:
        await message.answer(
            caption,
            **_entity_kwargs(caption_entities, parse_mode, caption=False),
            reply_markup=reply_markup,
        )
        return

    if len(items) == 1:
        media = items[0]
        kwargs = {
            "caption": caption,
            **_entity_kwargs(caption_entities, parse_mode, caption=True),
            "reply_markup": reply_markup,
        }
        if _is_video(media):
            await message.answer_video(
                video=_file_id(media),
                **kwargs,
            )
        else:
            await message.answer_photo(
                photo=_file_id(media),
                **kwargs,
            )
        return

    first_chunk = True
    for chunk in _media_chunks(items):
        if len(chunk) == 1:
            media = chunk[0]
            if _is_video(media):
                await message.answer_video(video=_file_id(media))
            else:
                await message.answer_photo(photo=_file_id(media))
            first_chunk = False
            continue

        media_group = []
        for index, media in enumerate(chunk):
            media_group.append(
                _input_media(
                    media,
                    caption=caption if first_chunk and index == 0 else None,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities if first_chunk and index == 0 else None,
                )
            )
        await message.answer_media_group(media=media_group)
        first_chunk = False

    if reply_markup:
        await message.answer(MEDIA_BUTTON_TEXT, reply_markup=reply_markup)


async def send_property_media_card(
    bot: Bot,
    *,
    chat_id,
    media_items: Iterable,
    caption: str,
    reply_markup=None,
    parse_mode: str | None = "HTML",
    caption_entities_json: list[dict] | None = None,
) -> None:
    """Bot-level variant used by scheduled/background sends."""
    items = property_media_items(media_items)
    caption_entities = load_message_entities(caption_entities_json)

    if not items:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            **_entity_kwargs(caption_entities, parse_mode, caption=False),
            reply_markup=reply_markup,
        )
        return

    if len(items) == 1:
        media = items[0]
        kwargs = {
            "caption": caption,
            **_entity_kwargs(caption_entities, parse_mode, caption=True),
            "reply_markup": reply_markup,
        }
        if _is_video(media):
            await bot.send_video(
                chat_id=chat_id,
                video=_file_id(media),
                **kwargs,
            )
        else:
            await bot.send_photo(
                chat_id=chat_id,
                photo=_file_id(media),
                **kwargs,
            )
        return

    first_chunk = True
    for chunk in _media_chunks(items):
        if len(chunk) == 1:
            media = chunk[0]
            if _is_video(media):
                await bot.send_video(chat_id=chat_id, video=_file_id(media))
            else:
                await bot.send_photo(chat_id=chat_id, photo=_file_id(media))
            first_chunk = False
            continue

        media_group = []
        for index, media in enumerate(chunk):
            media_group.append(
                _input_media(
                    media,
                    caption=caption if first_chunk and index == 0 else None,
                    parse_mode=parse_mode,
                    caption_entities=caption_entities if first_chunk and index == 0 else None,
                )
            )
        await bot.send_media_group(chat_id=chat_id, media=media_group)
        first_chunk = False

    if reply_markup:
        await bot.send_message(chat_id=chat_id, text=MEDIA_BUTTON_TEXT, reply_markup=reply_markup)
