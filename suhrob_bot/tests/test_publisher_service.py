import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.services import publisher_service
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
    async def test_publish_copies_source_message_for_channel_custom_emoji(self):
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


if __name__ == "__main__":
    unittest.main()
