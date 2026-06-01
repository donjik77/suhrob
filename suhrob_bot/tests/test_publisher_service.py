import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.services import publisher_service
from src.db.models import FileType
from src.services.publisher_service import PublisherService


class FakeBot:
    def __init__(self):
        self.calls = []

    async def copy_message(self, *args, **kwargs):
        self.calls.append(("copy_message", args, kwargs))
        return SimpleNamespace(message_id=99)

    async def send_message(self, *args, **kwargs):
        self.calls.append(("send_message", args, kwargs))
        return SimpleNamespace(message_id=100)

    async def send_photo(self, *args, **kwargs):
        self.calls.append(("send_photo", args, kwargs))
        return SimpleNamespace(message_id=101)

    async def send_video(self, *args, **kwargs):
        self.calls.append(("send_video", args, kwargs))
        return SimpleNamespace(message_id=102)

    async def send_media_group(self, *args, **kwargs):
        self.calls.append(("send_media_group", args, kwargs))
        return [
            SimpleNamespace(message_id=200 + index)
            for index, _media in enumerate(kwargs.get("media", []))
        ]


class FakeSession:
    def __init__(self, company):
        self.company = company

    async def get(self, _model, _id):
        return self.company


class FakePropertyRepository:
    updated_post_id = None
    prop = None

    def __init__(self, _session):
        pass

    async def get_by_id(self, _property_id):
        return self.prop

    async def update_telegram_post_id(self, _property_id, post_id):
        self.__class__.updated_post_id = post_id


class PublisherServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_copies_source_message_when_source_available(self):
        """copy_message is used whenever custom_text_source_chat_id is set,
        regardless of whether custom_emoji entities are present."""
        original_repo = publisher_service.PropertyRepository
        publisher_service.PropertyRepository = FakePropertyRepository
        try:
            FakePropertyRepository.updated_post_id = None
            FakePropertyRepository.prop = SimpleNamespace(
                id=7,
                company_id=1,
                media=[],
                custom_text="🏡 Premium",
                custom_text_entities_json=[
                    {
                        "type": "custom_emoji",
                        "offset": 0,
                        "length": 2,
                        "custom_emoji_id": "123456",
                    }
                ],
                custom_text_source_chat_id=123,
                custom_text_source_message_id=456,
                custom_text_source_has_media=False,
            )
            company = SimpleNamespace(telegram_channel_id="-1001", bot_username=None)
            bot = FakeBot()

            success, _message = await PublisherService(FakeSession(company), bot).publish(7)

            self.assertTrue(success)
            self.assertEqual(FakePropertyRepository.updated_post_id, "99")
            self.assertEqual([call[0] for call in bot.calls], ["copy_message"])
            kwargs = bot.calls[0][2]
            self.assertEqual(kwargs["chat_id"], "-1001")
            self.assertEqual(kwargs["from_chat_id"], 123)
            self.assertEqual(kwargs["message_id"], 456)
        finally:
            publisher_service.PropertyRepository = original_repo

    async def test_publish_copies_source_message_for_premium_emoji_without_entities(self):
        """Premium emojis are not captured in message.entities, so custom_text_entities_json
        may be empty even when the text contains premium emojis. The publisher must still
        use copy_message whenever custom_text_source_chat_id is available."""
        original_repo = publisher_service.PropertyRepository
        publisher_service.PropertyRepository = FakePropertyRepository
        try:
            FakePropertyRepository.updated_post_id = None
            FakePropertyRepository.prop = SimpleNamespace(
                id=8,
                company_id=1,
                media=[],
                custom_text="Hello with premium emoji",
                custom_text_entities_json=None,  # no entities captured
                custom_text_source_chat_id=777,
                custom_text_source_message_id=888,
                custom_text_source_has_media=False,
            )
            company = SimpleNamespace(telegram_channel_id="-1002", bot_username=None)
            bot = FakeBot()

            success, _message = await PublisherService(FakeSession(company), bot).publish(8)

            self.assertTrue(success)
            self.assertEqual(FakePropertyRepository.updated_post_id, "99")
            self.assertEqual([call[0] for call in bot.calls], ["copy_message"])
            kwargs = bot.calls[0][2]
            self.assertEqual(kwargs["chat_id"], "-1002")
            self.assertEqual(kwargs["from_chat_id"], 777)
            self.assertEqual(kwargs["message_id"], 888)
        finally:
            publisher_service.PropertyRepository = original_repo

    async def test_publish_sends_custom_text_media_as_single_album(self):
        original_repo = publisher_service.PropertyRepository
        publisher_service.PropertyRepository = FakePropertyRepository
        try:
            FakePropertyRepository.updated_post_id = None
            FakePropertyRepository.prop = SimpleNamespace(
                id=7,
                company_id=1,
                media=[
                    SimpleNamespace(file_id="photo-1", file_type=FileType.photo),
                    SimpleNamespace(file_id="photo-2", file_type=FileType.photo),
                ],
                custom_text="рџЏЎ Premium",
                custom_text_entities_json=[
                    {
                        "type": "custom_emoji",
                        "offset": 0,
                        "length": 2,
                        "custom_emoji_id": "123456",
                    }
                ],
                custom_text_source_chat_id=123,
                custom_text_source_message_id=456,
                custom_text_source_has_media=True,
            )
            company = SimpleNamespace(telegram_channel_id="-1001", bot_username=None)
            bot = FakeBot()

            success, _message = await PublisherService(FakeSession(company), bot).publish(7)

            self.assertTrue(success)
            self.assertEqual(FakePropertyRepository.updated_post_id, "200")
            self.assertEqual([call[0] for call in bot.calls], ["send_media_group"])
            media_group = bot.calls[0][2]["media"]
            self.assertEqual(len(media_group), 2)
            self.assertEqual(media_group[0].caption, FakePropertyRepository.prop.custom_text)
            self.assertEqual(media_group[0].caption_entities[0].type, "custom_emoji")
            self.assertEqual(media_group[1].media, "photo-2")
        finally:
            publisher_service.PropertyRepository = original_repo


if __name__ == "__main__":
    unittest.main()
