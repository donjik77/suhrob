import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.client.ai_consultation import (
    _clean_ai_reply_for_cards,
    _extract_property_card_ids,
    check_ai_limit,
)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl


class AILimitTest(unittest.IsolatedAsyncioTestCase):
    async def test_allows_until_daily_limit_then_blocks(self):
        redis = FakeRedis()

        self.assertEqual(await check_ai_limit(42, redis, daily_limit=2), (True, 1))
        self.assertEqual(await check_ai_limit(42, redis, daily_limit=2), (True, 2))
        self.assertEqual(await check_ai_limit(42, redis, daily_limit=2), (False, 3))

    async def test_sets_redis_ttl_only_on_first_daily_call(self):
        redis = FakeRedis()

        await check_ai_limit(42, redis, daily_limit=50)
        await check_ai_limit(42, redis, daily_limit=50)

        self.assertEqual(len(redis.expirations), 1)
        key = next(iter(redis.expirations))
        self.assertTrue(key.startswith("ai_calls:42:"))
        self.assertEqual(redis.expirations[key], 86400)

    async def test_counts_are_per_user(self):
        redis = FakeRedis()

        self.assertEqual(await check_ai_limit(1, redis, daily_limit=1), (True, 1))
        self.assertEqual(await check_ai_limit(2, redis, daily_limit=1), (True, 1))
        self.assertEqual(await check_ai_limit(1, redis, daily_limit=1), (False, 2))


class AIPropertyCardMarkerTest(unittest.TestCase):
    def test_extracts_card_markers_and_legacy_visible_ids(self):
        reply = "Tayyor jigar\n[CARD:25]\n1. **#ID_26** - Vokzal"

        self.assertEqual(_extract_property_card_ids(reply), [25, 26])

    def test_removes_card_marker_lines_from_client_reply(self):
        reply = "Tayyor jigar, kartochka qilib yuboryapman.\n[CARD:25]\n1. #ID_26 - Vokzal"

        cleaned = _clean_ai_reply_for_cards(reply)

        self.assertEqual(cleaned, "Tayyor jigar, kartochka qilib yuboryapman.")


if __name__ == "__main__":
    unittest.main()
