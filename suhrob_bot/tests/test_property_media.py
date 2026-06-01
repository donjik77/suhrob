import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.utils.property_media import answer_property_media_card, property_media_items
from src.db.models import FileType


class FakeMessage:
    def __init__(self):
        self.calls = []

    async def answer(self, *args, **kwargs):
        self.calls.append(("answer", args, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=1), message_id=len(self.calls))

    async def answer_photo(self, *args, **kwargs):
        self.calls.append(("photo", args, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=1), message_id=len(self.calls))

    async def answer_video(self, *args, **kwargs):
        self.calls.append(("video", args, kwargs))
        return SimpleNamespace(chat=SimpleNamespace(id=1), message_id=len(self.calls))

    async def answer_media_group(self, *args, **kwargs):
        self.calls.append(("group", args, kwargs))
        return [
            SimpleNamespace(chat=SimpleNamespace(id=1), message_id=len(self.calls) + index)
            for index, _media in enumerate(kwargs.get("media", []))
        ]


class PropertyMediaHelpersTest(unittest.IsolatedAsyncioTestCase):
    def test_property_media_items_accepts_model_like_objects_and_fsm_dicts(self):
        items = [
            SimpleNamespace(file_id="photo-id", file_type=FileType.photo),
            {"file_id": "video-id", "file_type": FileType.video},
            SimpleNamespace(file_id="other-id", file_type="document"),
        ]

        self.assertEqual(
            [item["file_id"] if isinstance(item, dict) else item.file_id for item in property_media_items(items)],
            ["photo-id", "video-id"],
        )

    async def test_answer_property_media_card_sends_album_and_keyboard_marker(self):
        message = FakeMessage()
        items = [
            SimpleNamespace(file_id="photo-id", file_type=FileType.photo),
            SimpleNamespace(file_id="video-id", file_type=FileType.video),
        ]

        await answer_property_media_card(
            message,
            media_items=items,
            caption="card",
            reply_markup="kb",
        )

        self.assertEqual([call[0] for call in message.calls], ["group", "answer"])
        group_media = message.calls[0][2]["media"]
        self.assertEqual(len(group_media), 2)
        self.assertEqual(group_media[0].caption, "card")
        self.assertEqual(message.calls[1][1][0], "👆")

    async def test_answer_property_media_card_sends_text_entities_without_media(self):
        message = FakeMessage()
        entities = [
            {
                "type": "custom_emoji",
                "offset": 0,
                "length": 2,
                "custom_emoji_id": "123456",
            }
        ]

        await answer_property_media_card(
            message,
            media_items=[],
            caption="🏡 Premium",
            parse_mode="HTML",
            caption_entities_json=entities,
        )

        self.assertEqual([call[0] for call in message.calls], ["answer"])
        kwargs = message.calls[0][2]
        self.assertIsNone(kwargs["parse_mode"])
        self.assertEqual(kwargs["entities"][0].type, "custom_emoji")
        self.assertEqual(kwargs["entities"][0].custom_emoji_id, "123456")

    async def test_answer_property_media_card_sends_album_caption_entities(self):
        message = FakeMessage()
        items = [
            SimpleNamespace(file_id="photo-id", file_type=FileType.photo),
            SimpleNamespace(file_id="video-id", file_type=FileType.video),
        ]
        entities = [
            {
                "type": "custom_emoji",
                "offset": 0,
                "length": 2,
                "custom_emoji_id": "123456",
            }
        ]

        await answer_property_media_card(
            message,
            media_items=items,
            caption="🏡 Premium",
            caption_entities_json=entities,
        )

        group_media = message.calls[0][2]["media"]
        self.assertIsNone(group_media[0].parse_mode)
        self.assertEqual(group_media[0].caption_entities[0].type, "custom_emoji")
        self.assertEqual(group_media[0].caption_entities[0].custom_emoji_id, "123456")

    async def test_answer_property_media_card_splits_over_ten_media(self):
        message = FakeMessage()
        items = [
            SimpleNamespace(file_id=f"photo-{index}", file_type=FileType.photo)
            for index in range(11)
        ]

        await answer_property_media_card(
            message,
            media_items=items,
            caption="card",
            reply_markup="kb",
        )

        self.assertEqual([call[0] for call in message.calls], ["group", "photo", "answer"])


if __name__ == "__main__":
    unittest.main()
