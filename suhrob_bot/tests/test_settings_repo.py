import unittest
from decimal import Decimal
from unittest.mock import AsyncMock

from src.db.repositories.settings_repo import SettingsRepository


class SettingsRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_get_decimal_returns_decimal_value(self):
        repo = SettingsRepository(session=None)
        repo.get = AsyncMock(return_value="12600.50")

        value = await repo.get_decimal("currency_rate_uzs_per_usd", Decimal("1"))

        self.assertEqual(value, Decimal("12600.50"))

    async def test_get_decimal_returns_default_for_missing_or_invalid_value(self):
        repo = SettingsRepository(session=None)

        repo.get = AsyncMock(return_value=None)
        self.assertEqual(await repo.get_decimal("missing", Decimal("12")), Decimal("12"))

        repo.get = AsyncMock(return_value="not-a-number")
        self.assertEqual(await repo.get_decimal("bad", Decimal("12")), Decimal("12"))


if __name__ == "__main__":
    unittest.main()
