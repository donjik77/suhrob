"""
Тесты моста Salebot: разбор вебхука, формат исходящего /message,
Instagram-рендер без карточек и приём телефона (п.5 ТЗ).
"""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")
os.environ.setdefault("SALEBOT_API_KEY", "test_key")

from src.services import instagram_bridge as bridge


def salebot_payload(**overrides):
    """Тело вебхука Salebot из ТЗ."""
    data = {
        "id": "abc",
        "client": {
            "id": 123,
            "recepient": "instagram_user_id",
            "client_type": 6,
            "name": "Sardor",
            "avatar": "",
            "created_at": "2026-07-26T10:00:00",
            "tag": "",
            "group": "",
        },
        "message": "salom",
        "attachments": [],
        "message_id": 45,
        "project_id": 1,
        "is_input": 1,
        "delivered": 1,
        "error_message": "",
    }
    data.update(overrides)
    return data


class ParseSalebotUpdateTest(unittest.TestCase):
    def test_parses_incoming_message(self):
        parsed = bridge.parse_salebot_update(salebot_payload())
        self.assertEqual(parsed["client_id"], 123)
        self.assertEqual(parsed["message"], "salom")
        self.assertEqual(parsed["first_name"], "Sardor")

    def test_ignores_bot_echo(self):
        """is_input=0 — это наш же ответ. Иначе бот отвечает сам себе."""
        self.assertIsNone(bridge.parse_salebot_update(salebot_payload(is_input=0)))

    def test_ignores_other_channel(self):
        """WhatsApp/Telegram на том же проекте не должны попадать в IG-ветку."""
        payload = salebot_payload()
        payload["client"] = {**payload["client"], "client_type": 1}
        self.assertIsNone(bridge.parse_salebot_update(payload))

    def test_accepts_configured_channel(self):
        payload = salebot_payload()
        payload["client"] = {**payload["client"],
                             "client_type": bridge.SALEBOT_IG_CLIENT_TYPE}
        self.assertIsNotNone(bridge.parse_salebot_update(payload))

    def test_missing_client_id_rejected(self):
        payload = salebot_payload()
        payload["client"] = {**payload["client"], "id": None}
        self.assertIsNone(bridge.parse_salebot_update(payload))

    def test_flat_payload_from_flow(self):
        """Ручной вызов из фло шлёт плоское тело."""
        parsed = bridge.parse_salebot_update(
            {"client_id": 777, "message": "uy kerak", "first_name": "Malika"}
        )
        self.assertEqual(parsed["client_id"], 777)
        self.assertEqual(parsed["first_name"], "Malika")

    def test_non_dict_rejected(self):
        self.assertIsNone(bridge.parse_salebot_update([1, 2, 3]))


class SyntheticUserIdTest(unittest.TestCase):
    """ID-схема не меняется: Instagram-клиент = отрицательный telegram_user_id."""

    def test_negative_id_from_salebot_client_id(self):
        client_id = bridge.parse_salebot_update(salebot_payload())["client_id"]
        self.assertEqual(-abs(client_id), -123)
        # Обратное преобразование, которым пользуется планировщик
        self.assertEqual(abs(-123), client_id)


class SendMessagePayloadTest(unittest.IsolatedAsyncioTestCase):
    """Формат POST /api/{KEY}/message."""

    async def asyncSetUp(self):
        self.captured = []
        self._orig_key = bridge.SALEBOT_API_KEY
        bridge.SALEBOT_API_KEY = "test_key"

        captured = self.captured

        class FakeResponse:
            status_code = 200
            content = b'{"status":"success"}'
            text = '{"status":"success"}'

            def json(self):
                return {"status": "success"}

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None):
                captured.append((url, json))
                return FakeResponse()

        self._orig_client = bridge.httpx.AsyncClient
        bridge.httpx.AsyncClient = FakeClient

    async def asyncTearDown(self):
        bridge.httpx.AsyncClient = self._orig_client
        bridge.SALEBOT_API_KEY = self._orig_key

    async def test_text_message_payload(self):
        ok = await bridge.send_salebot_message(123, text="salom")
        self.assertTrue(ok)
        url, payload = self.captured[0]
        self.assertEqual(url, "https://chatter.salebot.pro/api/test_key/message")
        self.assertEqual(payload, {"client_id": 123, "message": "salom"})

    async def test_photo_uses_attachment_fields(self):
        await bridge.send_salebot_message(
            123, attachment_url="https://host/media/5.jpg"
        )
        _url, payload = self.captured[0]
        self.assertEqual(payload["attachment_type"], "image")
        self.assertEqual(payload["attachment_url"], "https://host/media/5.jpg")

    async def test_buttons_format(self):
        await bridge.send_salebot_message(123, text="Rasm?", buttons=["Ha", "Yo'q"])
        _url, payload = self.captured[0]
        buttons = payload["buttons"]["buttons"]
        self.assertEqual(buttons[0],
                         {"type": "reply", "text": "Ha", "line": 0,
                          "index_in_line": 0})
        self.assertEqual(buttons[1]["index_in_line"], 1)

    async def test_empty_message_not_sent(self):
        ok = await bridge.send_salebot_message(123)
        self.assertTrue(ok)
        self.assertEqual(self.captured, [], "пустое сообщение слать не надо")

    async def test_blocks_sent_in_order(self):
        await bridge.send_salebot_blocks(123, [
            {"text": "Gagarin, 2 xona, $48 000"},
            {"attachment_url": "https://host/media/1.jpg"},
            {"text": "Rasmlarini ko'rasizmi?"},
        ])
        texts = [p.get("message") or p.get("attachment_url")
                 for _u, p in self.captured]
        self.assertEqual(texts, [
            "Gagarin, 2 xona, $48 000",
            "https://host/media/1.jpg",
            "Rasmlarini ko'rasizmi?",
        ])

    async def test_missing_key_fails_loudly(self):
        bridge.SALEBOT_API_KEY = ""
        ok = await bridge.send_salebot_message(123, text="salom")
        self.assertFalse(ok)
        self.assertEqual(self.captured, [])


class InstagramRenderTest(unittest.TestCase):
    """п.2 ТЗ: в Instagram карточек нет, фото — только по согласию."""

    def test_card_markers_stripped(self):
        reply = "Gagarin, 2 xona, $48000.\n[CARD:142]\nRasmlarini ko'rasizmi?"
        cleaned = bridge.clean_ai_reply(reply)
        self.assertNotIn("CARD", cleaned)
        self.assertIn("Rasmlarini", cleaned)

    def test_visible_id_stripped(self):
        cleaned = bridge.clean_ai_reply("Mana variant ID:25\nNarxi arzon")
        self.assertNotIn("25", cleaned)

    def test_affirmative_answers_trigger_photos(self):
        for answer in ["ha", "Ha", "ok", "mayli", "albatta", "rasm",
                       "ko'rsating", "да", "давай", "+"]:
            self.assertTrue(bridge.wants_photos(answer), answer)

    def test_negative_answers_do_not_trigger_photos(self):
        for answer in ["yo'q", "kerak emas", "boshqa variant bormi",
                       "3 xonali kerak"]:
            self.assertFalse(bridge.wants_photos(answer), answer)

    def test_property_mention_detected(self):
        self.assertTrue(bridge.mentions_property("Gagarin, 2 xona, $48000"))
        self.assertFalse(bridge.mentions_property("Ismingiz nima?"))

    def test_photo_question_detected(self):
        self.assertTrue(bridge.asks_about_photos("Rasmlarini ko'rasizmi?"))
        self.assertFalse(bridge.asks_about_photos("Byudjetingiz qancha?"))


class PhoneDetectionTest(unittest.TestCase):
    """п.5 ТЗ: номер долетает, а бюджет за номер не принимается."""

    def test_plain_number(self):
        self.assertEqual(bridge.find_phone_in_text("+998901234567"),
                         "+998901234567")

    def test_spaced_number(self):
        self.assertEqual(bridge.find_phone_in_text("+998 90 123 45 67"),
                         "+998901234567")

    def test_local_nine_digits(self):
        self.assertEqual(bridge.find_phone_in_text("901234567"), "+998901234567")

    def test_number_inside_sentence(self):
        self.assertEqual(
            bridge.find_phone_in_text("mening raqamim +998901234567, qo'ng'iroq qiling"),
            "+998901234567",
        )

    def test_budget_with_currency_word_not_a_phone(self):
        self.assertIsNone(bridge.find_phone_in_text("byudjetim 50000 dollar"))

    def test_bare_budget_not_a_phone(self):
        """
        Регрессия: 9-значная сумма без слова "so'm" раньше проходила как
        телефон, перехватывала сообщение, и клиент получал "Rahmat, agent
        bog'lanadi" вместо ответа на свой вопрос.
        """
        self.assertIsNone(bridge.find_phone_in_text("100000000"))
        self.assertIsNone(bridge.find_phone_in_text("120000000"))

    def test_operator_codes_accepted(self):
        for code in ("90", "91", "93", "94", "95", "97", "98", "99", "33", "88"):
            self.assertEqual(
                bridge.find_phone_in_text(f"{code}1234567"), f"+998{code}1234567"
            )

    def test_too_short_rejected(self):
        self.assertIsNone(bridge.find_phone_in_text("12345"))


class AgentConnectTriggerTest(unittest.TestCase):
    """Regex "хочу агента" должен ловить живые формулировки."""

    def test_real_phrasings_match(self):
        phrases = [
            "agent bilan bog'lang",
            "qo'ng'iroq qiling",
            "raqamingiz bormi",
            "gaplashsam bo'ladimi",
            "kelib ko'rsam bo'ladimi",
            "rieltor kerak",
            "menejer bilan aloqa",
            "позвоните мне",
            "хочу связаться с риелтором",
            "телефон дайте",
        ]
        for phrase in phrases:
            self.assertTrue(bridge._AGENT_CONNECT_RE.search(phrase), phrase)

    def test_unrelated_text_does_not_match(self):
        for phrase in ["3 xonali kvartira", "narxi qancha", "salom"]:
            self.assertIsNone(bridge._AGENT_CONNECT_RE.search(phrase), phrase)


class FollowupAnswerTest(unittest.TestCase):
    """п.4 ТЗ: Instagram-эквивалент callback followup:*."""

    def test_stop_answers(self):
        for answer in ["topdim rahmat", "kerak emas", "yozmang", "нашёл",
                       "отписаться"]:
            self.assertTrue(bridge._FOLLOWUP_STOP_RE.search(answer), answer)

    def test_yes_answers(self):
        for answer in ["ha hali izlayapman", "qidiryapman", "да", "ищу"]:
            self.assertTrue(bridge._FOLLOWUP_YES_RE.search(answer), answer)


if __name__ == "__main__":
    unittest.main()
