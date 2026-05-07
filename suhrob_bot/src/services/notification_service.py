from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.models import (
    Subscription, SubscriptionStatus, NotificationLog, NotificationType, User, UserRole, Company
)
from src.db.repositories.user_repo import UserRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.utils.currency import usd_to_uzs
from locales.uz import t
import structlog

logger = structlog.get_logger()


class NotificationService:
    def __init__(self, session: AsyncSession, bot: Bot):
        self.session = session
        self.bot = bot

    async def send_3day_reminders(self) -> None:
        now = datetime.utcnow()
        target_start = now + timedelta(days=3)
        target_end = target_start + timedelta(hours=1)

        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.period_end >= target_start,
                Subscription.period_end < target_end,
            )
        )
        subs = list(result.scalars().all())

        settings_repo = SettingsRepository(self.session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

        for sub in subs:
            already_sent = await self._already_sent(
                sub.company_id, sub.id, NotificationType.payment_reminder_3days
            )
            if already_sent:
                continue

            users = await self._get_company_users(sub.company_id)
            price_uzs = usd_to_uzs(sub.price_usd, rate)
            msg = t("notify_3days", price=int(sub.price_usd), price_uzs=price_uzs)

            for user in users:
                await self._send(user, msg)
                await self._log(user.id, sub.id, NotificationType.payment_reminder_3days)

            # Notify developer
            from src.config import settings as cfg
            company = await self.session.get(Company, sub.company_id)
            cname = company.name if company else "—"
            dev_msg = f"📅 Kompaniya {cname} obunasi 3 kundan so'ng tugaydi. Hisob avtomatik yuborilgan."
            try:
                await self.bot.send_message(chat_id=cfg.DEVELOPER_TELEGRAM_ID, text=dev_msg)
            except Exception as e:
                logger.error("notify_dev_error", error=str(e))

    async def expire_subscriptions(self) -> None:
        now = datetime.utcnow()

        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.period_end < now,
            )
        )
        subs = list(result.scalars().all())

        for sub in subs:
            sub.status = SubscriptionStatus.expired
            await self.session.commit()

            users = await self._get_company_users(sub.company_id)
            msg = t("notify_expired_director")
            for user in users:
                await self._send(user, msg)
                await self._log(user.id, sub.id, NotificationType.blocked)

            from src.config import settings as cfg
            company = await self.session.get(Company, sub.company_id)
            cname = company.name if company else "—"
            dev_msg = t("notify_expired_dev", company=cname)
            try:
                await self.bot.send_message(chat_id=cfg.DEVELOPER_TELEGRAM_ID, text=dev_msg)
            except Exception as e:
                logger.error("notify_dev_error", error=str(e))

    async def _already_sent(self, company_id: int, sub_id: int, ntype: NotificationType) -> bool:
        from sqlalchemy import func
        result = await self.session.execute(
            select(NotificationLog).where(
                NotificationLog.related_subscription_id == sub_id,
                NotificationLog.notification_type == ntype,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _get_company_users(self, company_id: int) -> list[User]:
        repo = UserRepository(self.session)
        return await repo.get_company_users(company_id)

    async def _send(self, user: User, text: str) -> None:
        try:
            await self.bot.send_message(chat_id=user.telegram_user_id, text=text)
        except Exception as e:
            logger.warning("send_notification_failed", user_id=user.telegram_user_id, error=str(e))

    async def _log(self, user_id: int, sub_id: int, ntype: NotificationType) -> None:
        log = NotificationLog(
            user_id=user_id,
            notification_type=ntype,
            related_subscription_id=sub_id,
        )
        self.session.add(log)
        await self.session.commit()
