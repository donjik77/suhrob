import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("DEVELOPER_TELEGRAM_ID", "1")

from src.bot.keyboards.agent import publish_options_kb
from src.bot.keyboards.payment import invoice_payment_method_kb
from src.db.models import SubscriptionStatus
from src.db.repositories.subscription_repo import SubscriptionRepository
from src.services.notification_service import _next_payment_price_usd


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _Repo(SubscriptionRepository):
    def __init__(self, sub, active=None):
        self.sub = sub
        self.active = active

    async def get_active(self, company_id: int):
        return self.active

    async def get_latest(self, company_id: int):
        return self.sub


class SubscriptionBillingTest(unittest.IsolatedAsyncioTestCase):
    async def test_missing_pending_and_expired_active_subscription_are_blocked(self):
        self.assertTrue(await _Repo(None).is_blocked(1))

        pending = SimpleNamespace(status=SubscriptionStatus.pending_payment, period_end=None)
        self.assertTrue(await _Repo(pending).is_blocked(1))

        expired_active = SimpleNamespace(
            status=SubscriptionStatus.active,
            period_end=_now() - timedelta(seconds=1),
        )
        self.assertTrue(await _Repo(expired_active).is_blocked(1))

    async def test_future_active_subscription_is_not_blocked(self):
        active = SimpleNamespace(
            status=SubscriptionStatus.active,
            period_end=_now() + timedelta(days=1),
        )
        self.assertFalse(await _Repo(active, active=active).is_blocked(1))

    async def test_pending_invoice_does_not_block_while_active_subscription_exists(self):
        active = SimpleNamespace(
            status=SubscriptionStatus.active,
            period_end=_now() + timedelta(days=5),
        )
        pending_invoice = SimpleNamespace(status=SubscriptionStatus.pending_payment, period_end=None)

        self.assertFalse(await _Repo(pending_invoice, active=active).is_blocked(1))

    def test_profile_subscription_queries_are_limited(self):
        source = Path("src/bot/handlers/director/profile.py").read_text(encoding="utf-8")

        self.assertIn("SubscriptionType.base", source)
        self.assertIn("SubscriptionType.instagram", source)
        self.assertGreaterEqual(source.count(".limit(1)"), 2)

    def test_subscription_middleware_covers_all_company_users_and_payment_flow(self):
        source = Path("src/bot/middlewares/subscription.py").read_text(encoding="utf-8")

        self.assertIn("UserRole.client, UserRole.agent, UserRole.director", source)
        self.assertIn('t("service_blocked_client")', source)
        self.assertIn("event.message or event.callback_query", source)
        self.assertIn('callback_data.startswith("pay_invoice_method:")', source)

    def test_invoice_sender_targets_staff_with_invoice_specific_buttons(self):
        source = Path("src/bot/handlers/developer/payments.py").read_text(encoding="utf-8")

        self.assertIn("u.role in (UserRole.agent, UserRole.director)", source)
        self.assertIn("invoice_payment_method_kb(sub.id)", source)

    def test_invoice_payment_handler_exists(self):
        source = Path("src/bot/handlers/director/subscription.py").read_text(encoding="utf-8")

        self.assertIn('F.data.startswith("pay_invoice_method:")', source)

    def test_trial_subscription_next_payment_uses_monthly_price(self):
        self.assertEqual(
            _next_payment_price_usd(Decimal("0"), Decimal("49")),
            Decimal("49"),
        )
        self.assertEqual(
            _next_payment_price_usd(Decimal("25"), Decimal("49")),
            Decimal("25"),
        )


class PublishKeyboardTest(unittest.TestCase):
    def test_invoice_payment_buttons_carry_subscription_id(self):
        kb = invoice_payment_method_kb(77)

        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "pay_invoice_method:77:click")
        self.assertEqual(kb.inline_keyboard[0][1].callback_data, "pay_invoice_method:77:humo")
        self.assertEqual(kb.inline_keyboard[1][0].callback_data, "pay_invoice_method:77:uzcard")
        self.assertEqual(kb.inline_keyboard[1][1].callback_data, "pay_invoice_method:77:crypto")

    def test_publish_buttons_carry_property_id(self):
        kb = publish_options_kb(42)

        self.assertEqual(kb.inline_keyboard[0][0].callback_data, "ap_pub:now:42")
        self.assertEqual(kb.inline_keyboard[1][0].callback_data, "ap_pub:schedule:42")
        self.assertEqual(kb.inline_keyboard[2][0].callback_data, "ap_pub:save_only:42")

    def test_publish_handler_does_not_depend_on_fsm_state_filter(self):
        source = Path("src/bot/handlers/agent/add_property.py").read_text(encoding="utf-8")

        self.assertIn('@router.callback_query(F.data.startswith("ap_pub:"))', source)


if __name__ == "__main__":
    unittest.main()
