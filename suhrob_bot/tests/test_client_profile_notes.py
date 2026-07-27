"""
п.3 ТЗ — память бота: имя / пол / промокод переживают окно истории.

ClientProfile не имеет колонок под client_name, client_gender и promo_code.
qualify_client их извлекал, но оба upsert-а (Telegram и Instagram) писали в
notes только summary — то есть выбрасывали. Из-за этого промокод жил ровно
столько, сколько держалось окно истории, и на длинном диалоге бот выдавал
новый код.
"""
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.services.ai_service import (
    format_client_profile, merge_profile_notes, profile_summary,
    profile_to_context, unpack_profile_notes,
)


class ProfileRow:
    """Подставная ORM-строка ClientProfile."""

    def __init__(self, notes=None, **kwargs):
        self.notes = notes
        self.budget_min_usd = kwargs.get("budget_min_usd")
        self.budget_max_usd = kwargs.get("budget_max_usd")
        self.preferred_districts = kwargs.get("preferred_districts")
        self.preferred_rooms = kwargs.get("preferred_rooms")
        self.purchase_timeline = kwargs.get("purchase_timeline")
        self.payment_method = kwargs.get("payment_method")
        self.qualification_score = kwargs.get("qualification_score", 0)


class NotesRoundTripTest(unittest.TestCase):
    def test_pack_and_unpack(self):
        notes = merge_profile_notes(None, {
            "summary": "2 xona qidiryapti",
            "client_name": "Sardor",
            "client_gender": "male",
            "promo_code": "SUHROB-0000",
        })
        data = unpack_profile_notes(notes)
        self.assertEqual(data["client_name"], "Sardor")
        self.assertEqual(data["client_gender"], "male")
        self.assertEqual(data["promo_code"], "SUHROB-0000")
        self.assertEqual(data["summary"], "2 xona qidiryapti")

    def test_legacy_plain_text_notes_read_as_summary(self):
        """Строки, записанные до фикса, не должны ломать чтение."""
        data = unpack_profile_notes("Mijoz Gagarinda uy qidiryapti")
        self.assertEqual(data["summary"], "Mijoz Gagarinda uy qidiryapti")
        self.assertIsNone(data["promo_code"])

    def test_broken_json_falls_back_to_summary(self):
        data = unpack_profile_notes("{not json")
        self.assertEqual(data["summary"], "{not json")

    def test_empty_notes(self):
        self.assertIsNone(unpack_profile_notes(None)["promo_code"])
        self.assertEqual(unpack_profile_notes("")["summary"], "")


class PromoCodeSurvivalTest(unittest.TestCase):
    """Главная регрессия п.3."""

    def test_promo_code_survives_update_without_it(self):
        first = merge_profile_notes(None, {
            "summary": "Tanishdi",
            "client_name": "Sardor",
            "promo_code": "SUHROB-0000",
        })
        # Следующая квалификация промокод не увидела (он ушёл за окно истории)
        second = merge_profile_notes(first, {
            "summary": "Byudjet 50000",
            "promo_code": None,
        })
        data = unpack_profile_notes(second)
        self.assertEqual(data["promo_code"], "SUHROB-0000",
                         "промокод не должен затираться пустым значением")
        self.assertEqual(data["client_name"], "Sardor")
        self.assertEqual(data["summary"], "Byudjet 50000",
                         "summary обновляется, когда он есть")

    def test_name_survives_many_updates(self):
        notes = merge_profile_notes(None, {"client_name": "Malika",
                                           "client_gender": "female"})
        for i in range(15):
            notes = merge_profile_notes(notes, {"summary": f"xabar {i}"})
        data = unpack_profile_notes(notes)
        self.assertEqual(data["client_name"], "Malika")
        self.assertEqual(data["client_gender"], "female")

    def test_new_promo_code_overwrites_only_when_present(self):
        notes = merge_profile_notes(None, {"promo_code": "SUHROB-1111"})
        notes = merge_profile_notes(notes, {"promo_code": "SUHROB-2222"})
        self.assertEqual(unpack_profile_notes(notes)["promo_code"], "SUHROB-2222")


class ProfileToContextTest(unittest.IsolatedAsyncioTestCase):
    """Оба канала собирают контекст одним и тем же сборщиком."""

    async def test_context_includes_notes_fields(self):
        row = ProfileRow(
            notes=json.dumps({
                "summary": "Jiddiy mijoz",
                "client_name": "Sardor",
                "client_gender": "male",
                "promo_code": "SUHROB-0000",
            }),
            budget_max_usd=50000,
            preferred_districts=["Gagarin"],
        )
        ctx = profile_to_context(row)
        self.assertEqual(ctx["client_name"], "Sardor")
        self.assertEqual(ctx["promo_code"], "SUHROB-0000")
        self.assertEqual(ctx["preferred_districts"], ["Gagarin"])

    async def test_none_row_gives_empty_context(self):
        self.assertEqual(profile_to_context(None), {})

    async def test_promo_reaches_prompt_text(self):
        """Промокод должен долетать до текста промпта, а не теряться по пути."""
        row = ProfileRow(notes=merge_profile_notes(None, {
            "client_name": "Sardor",
            "promo_code": "SUHROB-0000",
        }))
        text = await format_client_profile(profile_to_context(row))
        self.assertIn("SUHROB-0000", text)
        self.assertIn("Sardor", text)
        self.assertIn("YANGI KOD YARATMA", text)

    async def test_unknown_name_asks_to_introduce(self):
        text = await format_client_profile({})
        self.assertIn("NOMA'LUM", text)


class ProfileSummaryTest(unittest.TestCase):
    """Агенту в уведомление должен уходить текст, а не сырой JSON."""

    def test_summary_extracted_from_json(self):
        notes = merge_profile_notes(None, {"summary": "Naqd pulga oladi",
                                           "promo_code": "SUHROB-0000"})
        self.assertEqual(profile_summary(notes), "Naqd pulga oladi")
        self.assertNotIn("{", profile_summary(notes))

    def test_summary_from_legacy_notes(self):
        self.assertEqual(profile_summary("Eski yozuv"), "Eski yozuv")

    def test_summary_empty(self):
        self.assertEqual(profile_summary(None), "")


if __name__ == "__main__":
    unittest.main()
