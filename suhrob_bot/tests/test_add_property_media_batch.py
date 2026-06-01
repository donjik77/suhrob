import asyncio
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.agent import add_property


class FakeState:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


class FakeMessage:
    def __init__(self, calls, media_group_id=None):
        self.calls = calls
        self.media_group_id = media_group_id
        self.chat = SimpleNamespace(id=1)
        self.from_user = SimpleNamespace(id=2)

    async def answer(self, *args, **kwargs):
        self.calls.append(("answer", args, kwargs))
        return SimpleNamespace(message_id=len(self.calls))


class AddPropertyMediaBatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        add_property._MEDIA_GROUP_BUFFERS.clear()
        add_property._MEDIA_GROUP_TASKS.clear()
        add_property._MEDIA_STATE_LOCKS.clear()
        self.original_delay = add_property.MEDIA_GROUP_COLLECT_DELAY
        add_property.MEDIA_GROUP_COLLECT_DELAY = 0.01

    async def asyncTearDown(self):
        for task in list(add_property._MEDIA_GROUP_TASKS.values()):
            task.cancel()
        await asyncio.sleep(0)
        add_property._MEDIA_GROUP_BUFFERS.clear()
        add_property._MEDIA_GROUP_TASKS.clear()
        add_property._MEDIA_STATE_LOCKS.clear()
        add_property.MEDIA_GROUP_COLLECT_DELAY = self.original_delay

    async def test_media_group_is_counted_once_with_one_button_message(self):
        calls = []
        state = FakeState({"photos": [], "videos": []})

        for index in range(5):
            message = FakeMessage(calls, media_group_id="album-1")
            queued = add_property._queue_media_group_item(
                message,
                state,
                photos=[{"file_id": f"photo-{index}"}],
            )
            self.assertTrue(queued)

        await asyncio.sleep(0.05)

        self.assertEqual([item["file_id"] for item in state.data["photos"]], [
            "photo-0",
            "photo-1",
            "photo-2",
            "photo-3",
            "photo-4",
        ])
        self.assertEqual(len(calls), 1)
        self.assertIn("5 ta rasm", calls[0][1][0])
        self.assertIn("reply_markup", calls[0][2])

    async def test_separate_video_joins_pending_photo_batch(self):
        calls = []
        state = FakeState({"photos": [], "videos": []})

        add_property._queue_media_group_item(
            FakeMessage(calls, media_group_id="album-1"),
            state,
            photos=[{"file_id": "photo-1"}],
        )
        add_property._queue_media_group_item(
            FakeMessage(calls),
            state,
            videos=[{"file_id": "video-1"}],
        )

        await asyncio.sleep(0.05)

        self.assertEqual([item["file_id"] for item in state.data["photos"]], ["photo-1"])
        self.assertEqual([item["file_id"] for item in state.data["videos"]], ["video-1"])
        self.assertEqual(len(calls), 1)
        self.assertIn("1 ta rasm", calls[0][1][0])
        self.assertIn("1 ta video", calls[0][1][0])

    async def test_photo_limit_is_applied_to_whole_batch(self):
        calls = []
        state = FakeState({"photos": [], "videos": []})
        message = FakeMessage(calls)

        await add_property._add_media_batch(
            message,
            state,
            photos=[{"file_id": f"photo-{index}"} for index in range(12)],
        )

        self.assertEqual(len(state.data["photos"]), 10)
        self.assertEqual(len(calls), 1)
        self.assertIn("10 ta rasm", calls[0][1][0])
        self.assertIn("Limit", calls[0][1][0])


if __name__ == "__main__":
    unittest.main()
