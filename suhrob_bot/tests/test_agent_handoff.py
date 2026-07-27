"""
Связывание клиента с агентом (п.5 ТЗ) + отсутствие второго блокирующего
вызова LLM на горячем пути.

Проверяется цепочка: "хочу агента" -> запрос номера -> номер принят ->
агент получает уведомление с телефоном и контекстом.
"""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.handlers.client import ai_consultation as consult
from src.services import ai_service, instagram_bridge as bridge


class WantsAgentDetectionTest(unittest.TestCase):
    """Оба канала должны реагировать на одни и те же формулировки."""

    PHRASES = [
        "agent bilan bog'lang",
        "qo'ng'iroq qiling",
        "raqamingiz bormi",
        "gaplashsam bo'ladimi",
        "rieltor kerak",
        "kelib ko'rsam bo'ladimi",
        "позвоните мне",
        "хочу связаться с риелтором",
    ]

    def test_telegram_detects_all(self):
        for phrase in self.PHRASES:
            self.assertTrue(consult._wants_agent_connection(phrase), phrase)

    def test_instagram_detects_all(self):
        for phrase in self.PHRASES:
            self.assertTrue(bridge._AGENT_CONNECT_RE.search(phrase), phrase)

    def test_both_channels_agree(self):
        """Регексы каналов не должны расходиться."""
        for phrase in self.PHRASES + ["salom", "narxi qancha", "3 xonali"]:
            tg = bool(consult._wants_agent_connection(phrase))
            ig = bool(bridge._AGENT_CONNECT_RE.search(phrase))
            self.assertEqual(tg, ig, phrase)

    def test_small_talk_does_not_trigger(self):
        for phrase in ["salom", "rahmat", "narxi qancha", "3 xonali kvartira"]:
            self.assertFalse(consult._wants_agent_connection(phrase), phrase)


class LeadNotificationPayloadTest(unittest.IsolatedAsyncioTestCase):
    """Что именно уходит агенту в уведомлении."""

    async def test_summary_is_text_not_raw_json(self):
        """
        notes теперь JSON. Если брать его как есть, агент получит
        '{"summary": ...}' вместо человеческого текста.
        """
        notes = ai_service.merge_profile_notes(None, {
            "summary": "Naqd pulga oladi, Gagarin tumani",
            "client_name": "Sardor",
            "promo_code": "SUHROB-0000",
        })
        summary = ai_service.profile_summary(notes)
        self.assertEqual(summary, "Naqd pulga oladi, Gagarin tumani")
        self.assertNotIn("{", summary)
        self.assertNotIn("promo_code", summary)

    async def test_instagram_profile_qualification_uses_summary(self):
        class FakeProfile:
            qualification_score = 85
            budget_min_usd = 40000
            budget_max_usd = 50000
            preferred_districts = ["Gagarin"]
            preferred_rooms = [2]
            purchase_timeline = "urgent"
            payment_method = "cash"
            notes = ai_service.merge_profile_notes(
                None, {"summary": "Jiddiy mijoz", "promo_code": "SUHROB-0000"}
            )

        data = bridge._profile_qualification(FakeProfile())
        self.assertEqual(data["summary"], "Jiddiy mijoz")
        self.assertEqual(data["qualification_score"], 85)
        self.assertEqual(data["preferred_districts"], ["Gagarin"])

    async def test_missing_profile_still_produces_payload(self):
        """Лид не должен теряться из-за отсутствия профиля."""
        data = bridge._profile_qualification(None)
        self.assertEqual(data["qualification_score"], 0)
        self.assertTrue(data["summary"], "резюме не должно быть пустым")


class PhoneToAgentChainTest(unittest.TestCase):
    """Номер, присланный любым путём, должен нормализоваться одинаково."""

    def test_same_number_various_formats(self):
        variants = [
            "+998901234567",
            "998901234567",
            "901234567",
            "+998 90 123 45 67",
            "mening raqamim +998901234567",
        ]
        for raw in variants:
            self.assertEqual(bridge.find_phone_in_text(raw), "+998901234567", raw)

    def test_budget_is_not_mistaken_for_phone(self):
        """
        Регрессия: бюджет перехватывал сообщение, AI не вызывался, и клиент
        вместо ответа получал "Rahmat, agent bog'lanadi".
        """
        for raw in ["100000000", "byudjetim 50000 dollar", "50000",
                    "narxi 120000000"]:
            self.assertIsNone(bridge.find_phone_in_text(raw), raw)


def _executable_source(func) -> str:
    """
    Исходник функции без комментариев.

    Комментарии здесь цитируют старый код ("раньше стоял await
    qualify_client"), поэтому проверять надо только исполняемые строки.
    """
    import inspect
    lines = []
    for line in inspect.getsource(func).splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            lines.append(code)
    return "\n".join(lines)


class HotPathHasNoBlockingQualifyTest(unittest.TestCase):
    """
    Регрессия по скорости: qualify_client — второй вызов LLM подряд.
    Он обязан уходить в фон, а не держать ответ клиенту.
    """

    def test_telegram_handler_backgrounds_qualification(self):
        source = _executable_source(consult.handle_consultation_message)
        self.assertNotIn("await ai_service.qualify_client", source,
                         "квалификация не должна блокировать ответ клиенту")
        self.assertIn("_qualify_in_background", source)

    def test_reply_is_sent_before_qualification(self):
        """Ответ клиенту должен уходить РАНЬШЕ постановки фоновой задачи."""
        source = _executable_source(consult.handle_consultation_message)
        self.assertLess(
            source.index("await message.answer(reply)"),
            source.index("_qualify_in_background"),
            "message.answer должен идти до квалификации",
        )

    def test_background_helpers_exist(self):
        self.assertTrue(callable(consult._qualify_in_background))
        self.assertTrue(callable(consult._notify_agent_background))

    def test_instagram_handler_backgrounds_qualification(self):
        source = _executable_source(bridge._process_and_reply)
        self.assertNotIn("await ai_service.qualify_client", source)
        self.assertIn("_qualify_in_background", source)

    def test_service_chat_has_timeout(self):
        """Без таймаута AsyncOpenAI ждёт до 600 секунд."""
        source = _executable_source(ai_service._chat)
        self.assertIn("timeout=timeout", source)

    def test_qualify_uses_main_model(self):
        """
        qualify_client должен идти на быструю MAIN_MODEL, а не на дефолтную
        бесплатную reasoning-модель из настроек.
        """
        source = _executable_source(ai_service.qualify_client)
        self.assertIn("model=MAIN_MODEL", source)


if __name__ == "__main__":
    unittest.main()
