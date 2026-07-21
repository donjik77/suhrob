import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.client.property_access import get_active_property_for_client, resolve_client_company_id


class ClientPropertyAccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_company_denies_property_access_without_query(self):
        class Session:
            async def execute(self, _stmt):
                raise AssertionError("session should not be queried without company")

        prop = await get_active_property_for_client(123, None, Session())

        self.assertIsNone(prop)

    def test_company_id_falls_back_to_user_scope(self):
        user = SimpleNamespace(company_id=42)

        self.assertEqual(resolve_client_company_id(None, user), 42)

    async def test_company_id_can_be_passed_directly(self):
        class Result:
            def scalar_one_or_none(self):
                return "property"

        class Session:
            async def execute(self, _stmt):
                return Result()

        prop = await get_active_property_for_client(123, 42, Session())

        self.assertEqual(prop, "property")


if __name__ == "__main__":
    unittest.main()
