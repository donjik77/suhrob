import os
import unittest
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.director import balance


class TopUpPaymentHelpersTest(unittest.TestCase):
    def test_parse_amount_accepts_usd_text(self):
        self.assertEqual(balance._parse_amount("$49"), Decimal("49.00"))
        self.assertEqual(balance._parse_amount("75,5"), Decimal("75.50"))

    def test_parse_amount_rejects_invalid_values(self):
        for raw in ("", "abc", "0", "-10", "100001"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    balance._parse_amount(raw)

    def test_method_keyboard_keeps_amount_and_method(self):
        kb = balance._method_kb(Decimal("49.00"))
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "topup_method:49:click")
        self.assertEqual(kb.inline_keyboard[3][0].callback_data, "topup_method:49:crypto")

    def test_cancel_and_developer_callbacks_match_handlers(self):
        cancel_kb = balance._cancel_topup_kb()
        developer_kb = balance._developer_topup_kb(123)

        self.assertEqual(cancel_kb.inline_keyboard[0][0].callback_data, "topup_cancel")
        self.assertEqual(developer_kb.inline_keyboard[0][0].callback_data, "tx_confirm:123")
        self.assertEqual(developer_kb.inline_keyboard[0][1].callback_data, "tx_reject:123")

    def test_card_instruction_contains_requisites_and_amounts(self):
        text = balance._topup_instruction(
            method="click",
            amount=Decimal("49.00"),
            amount_uzs=Decimal("617400.00"),
            card="8600 0000 0000 0000",
            holder="Suhrob HOUSE",
        )

        self.assertIn("Click orqali", text)
        self.assertIn("8600 0000 0000 0000", text)
        self.assertIn("Suhrob HOUSE", text)
        self.assertIn("$49", text)
        self.assertIn("617 400", text)


if __name__ == "__main__":
    unittest.main()
