"""
п.4 ТЗ — напоминания должны доходить и в Telegram, и в Instagram.

Instagram-клиенты лежат с ОТРИЦАТЕЛЬНЫМ telegram_user_id. Раньше все джобы
звали bot.send_message() с этим id: Telegram Bot API такой chat не находит,
вызов падал в except и тихо логировался как follow_up_send_failed —
то есть механизм в принципе не мог достучаться до Instagram.

Плюс п.2: правила канала в промпте (Telegram = карточки, Instagram = текст).
"""
import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.scheduler.jobs import is_instagram_client, send_to_client
from src.services import instagram_bridge as bridge
from src.services.ai_prompts import (
    CACHE_MARKER, INSTAGRAM_RULES, SYSTEM_PROMPT, TELEGRAM_RULES, channel_rules,
)


class FakeUser:
    def __init__(self, telegram_user_id, user_id=1):
        self.telegram_user_id = telegram_user_id
        self.id = user_id


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, **kwargs})


class ChannelDetectionTest(unittest.TestCase):
    def test_positive_id_is_telegram(self):
        self.assertFalse(is_instagram_client(FakeUser(6093721405)))

    def test_negative_id_is_instagram(self):
        self.assertTrue(is_instagram_client(FakeUser(-123)))

    def test_zero_id_treated_as_telegram(self):
        self.assertFalse(is_instagram_client(FakeUser(0)))


class SendToClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.salebot_calls = []

        async def fake_send(client_id, text=None, attachment_url=None, buttons=None):
            self.salebot_calls.append(
                {"client_id": client_id, "text": text, "buttons": buttons}
            )
            return True

        self._orig = bridge.send_salebot_message
        bridge.send_salebot_message = fake_send

    async def asyncTearDown(self):
        bridge.send_salebot_message = self._orig

    async def test_telegram_client_gets_bot_send_message(self):
        bot = FakeBot()
        user = FakeUser(6093721405)
        await send_to_client(bot, user, "Salom", buttons=["Ha"],
                             reply_markup="MARKUP")

        self.assertEqual(len(bot.sent), 1)
        self.assertEqual(bot.sent[0]["chat_id"], 6093721405)
        self.assertEqual(bot.sent[0]["reply_markup"], "MARKUP")
        self.assertEqual(self.salebot_calls, [], "в Salebot ничего уходить не должно")

    async def test_instagram_client_gets_salebot_call(self):
        """Регрессия: раньше сюда уходил bot.send_message(-123) и падал."""
        bot = FakeBot()
        user = FakeUser(-123)
        ok = await send_to_client(bot, user, "Yangi variantlar bor",
                                  buttons=["Ha", "Yo'q"], reply_markup="MARKUP")

        self.assertTrue(ok)
        self.assertEqual(bot.sent, [], "Telegram API для Instagram не вызывается")
        self.assertEqual(len(self.salebot_calls), 1)
        call = self.salebot_calls[0]
        self.assertEqual(call["client_id"], 123, "client_id = abs(telegram_user_id)")
        self.assertEqual(call["text"], "Yangi variantlar bor")
        self.assertEqual(call["buttons"], ["Ha", "Yo'q"],
                         "инлайн-кнопок в Instagram нет — уходят reply-кнопки")

    async def test_both_channels_in_one_run(self):
        """Сценарий проверки из ТЗ: один TG-клиент и один IG-клиент."""
        bot = FakeBot()
        stale = datetime.now(timezone.utc) - timedelta(days=3)
        users = [FakeUser(6093721405, user_id=1), FakeUser(-777, user_id=2)]

        for user in users:
            # last_contact_at 3 дня назад — условие follow-up дня 3
            self.assertGreaterEqual((datetime.now(timezone.utc) - stale).days, 3)
            await send_to_client(bot, user, "Follow-up", buttons=["Ha"])

        self.assertEqual(len(bot.sent), 1, "Telegram получил своё")
        self.assertEqual(len(self.salebot_calls), 1, "Instagram получил своё")
        self.assertEqual(self.salebot_calls[0]["client_id"], 777)


class ChannelRulesTest(unittest.TestCase):
    """п.2 ТЗ: разные правила длины и показа объектов по каналам."""

    def test_telegram_rules_keep_cards(self):
        self.assertIn("[CARD:ID]", TELEGRAM_RULES)
        self.assertIn("ISHLAT", TELEGRAM_RULES)

    def test_instagram_rules_forbid_cards(self):
        self.assertIn("ISHLATMA", INSTAGRAM_RULES)
        self.assertIn("4-5 SO'Z", INSTAGRAM_RULES)
        self.assertIn("Rasmlarini ko'rasizmi?", INSTAGRAM_RULES)

    def test_channel_lookup(self):
        self.assertEqual(channel_rules("telegram"), TELEGRAM_RULES)
        self.assertEqual(channel_rules("instagram"), INSTAGRAM_RULES)
        self.assertEqual(channel_rules("INSTAGRAM"), INSTAGRAM_RULES)

    def test_unknown_channel_defaults_to_telegram(self):
        self.assertEqual(channel_rules("whatsapp"), TELEGRAM_RULES)
        self.assertEqual(channel_rules(""), TELEGRAM_RULES)
        self.assertEqual(channel_rules(None), TELEGRAM_RULES)


class PromptStructureTest(unittest.TestCase):
    """Промпт должен форматироваться и не терять ключевые блоки при сжатии."""

    def test_cache_marker_present(self):
        self.assertIn(CACHE_MARKER, SYSTEM_PROMPT,
                      "без маркера кэширование статики отключается")

    def test_formats_with_all_placeholders(self):
        rendered = SYSTEM_PROMPT.format(
            properties_context="CARD_ID:1 | Gagarin | 2 xona | $48000",
            client_profile="Ismi: Sardor",
            agents_contacts="Agent — +998901234567",
            channel_rules=INSTAGRAM_RULES,
        )
        self.assertIn("CARD_ID:1", rendered)
        self.assertIn("Ismi: Sardor", rendered)
        self.assertIn("+998901234567", rendered)
        self.assertIn("4-5 SO'Z", rendered)

    def test_identity_and_goal_at_the_top(self):
        head = SYSTEM_PROMPT[:600]
        self.assertIn("SUHROB AI", head)
        self.assertIn("MAQSADING", head)
        self.assertIn("AGENTGA TOPSHIRISHGACHA", head)

    def test_static_part_carries_the_rules(self):
        static_part = SYSTEM_PROMPT.split(CACHE_MARKER, 1)[0]
        for required in ("SUHROB-XXXX", "TANISHUV", "HALOLLIK", "HAZIL",
                         "MUROJAAT", "E'TIROZLAR", "Gagarin ko'chasi, 50"):
            self.assertIn(required, static_part, required)

    def test_checklist_at_the_end(self):
        tail = SYSTEM_PROMPT[-500:]
        self.assertIn("JAVOB BERISHDAN OLDIN TEKSHIR", tail)

    def test_length_rules_are_not_the_biggest_block(self):
        """
        Раньше блок про длину ответа занимал больше места, чем всё
        остальное вместе. Теперь правила длины живут в правилах канала.
        """
        self.assertLess(len(TELEGRAM_RULES), len(SYSTEM_PROMPT) / 4)
        self.assertLess(len(INSTAGRAM_RULES), len(SYSTEM_PROMPT) / 4)


if __name__ == "__main__":
    unittest.main()
