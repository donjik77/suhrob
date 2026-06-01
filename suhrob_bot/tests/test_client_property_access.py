import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.client.property_access import get_active_property_for_client


class ClientPropertyAccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_company_denies_property_access_without_query(self):
        class Session:
            async def execute(self, _stmt):
                raise AssertionError("session should not be queried without company")

        prop = await get_active_property_for_client(123, None, Session())

        self.assertIsNone(prop)


if __name__ == "__main__":
    unittest.main()
