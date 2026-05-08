import os
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock

from src.db.repositories.settings_repo import SettingsRepository


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _SessionStub:
    def __init__(self, value):
        self.value = value

    async def execute(self, _stmt):
        return _ScalarResult(self.value)


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

    async def test_get_falls_back_to_env_when_db_value_is_empty(self):
        os.environ["PAYMENT_CLICK_CARD"] = "8600123412341234"
        try:
            repo = SettingsRepository(_SessionStub(""))

            self.assertEqual(
                await repo.get("payment_click_card", "missing"),
                "8600123412341234",
            )
        finally:
            os.environ.pop("PAYMENT_CLICK_CARD", None)

    async def test_qr_file_id_accepts_short_env_alias(self):
        os.environ["CLICK_QR"] = "telegram-file-id"
        try:
            repo = SettingsRepository(_SessionStub(None))

            self.assertEqual(
                await repo.get("payment_click_qr_file_id"),
                "telegram-file-id",
            )
        finally:
            os.environ.pop("CLICK_QR", None)


if __name__ == "__main__":
    unittest.main()
