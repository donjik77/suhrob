from datetime import datetime, timedelta
from decimal import Decimal

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import (
    Subscription, SubscriptionStatus, NotificationLog, NotificationType, User, UserRole, Company,
    UserBalance, BalanceTransaction, TransactionType, TransactionStatus,
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

    async def send_7day_reminders(self) -> None:
        now = datetime.utcnow()
        target_start = now + timedelta(days=7)
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
                sub.company_id, sub.id, NotificationType.payment_reminder_7days
            )
            if already_sent:
                continue

            # Check director balance
            director = await self._get_director(sub.company_id)
            has_balance = False
            if director and director.balance:
                has_balance = director.balance.balance_usd >= sub.price_usd

            users = await self._get_company_users(sub.company_id)
            price_uzs = usd_to_uzs(sub.price_usd, rate)
            balance_status = "✅ Yetarli" if has_balance else "⚠️ Yetarli emas"
            msg = (
                f"⏰ <b>Obuna 7 kundan so'ng tugaydi!</b>\n\n"
                f"Muddat: {sub.period_end.strftime('%d.%m.%Y')}\n"
                f"Narxi: ${int(sub.price_usd)} (~{price_uzs:,} so'm)\n"
                f"Balans holati: {balance_status}"
            )

            for user in users:
                await self._send(user, msg)
                await self._log(user.id, sub.id, NotificationType.payment_reminder_7days)

    async def expire_subscriptions(self) -> None:
        now = datetime.utcnow()

        result = await self.session.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.active,
                Subscription.period_end < now,
            )
        )
        subs = list(result.scalars().all())

        settings_repo = SettingsRepository(self.session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

        for sub in subs:
            director = await self._get_director(sub.company_id)
            auto_charged = False

            if director and director.balance:
                balance: UserBalance = director.balance
                price = Decimal(str(sub.price_usd))
                if balance.balance_usd >= price:
                    # Deduct and renew
                    balance.balance_usd -= price
                    tx = BalanceTransaction(
                        user_id=director.id,
                        amount_usd=-price,
                        transaction_type=TransactionType.subscription_charge,
                        description=f"Avtomatik obuna yangilash: {sub.subscription_type}",
                        related_subscription_id=sub.id,
                        status=TransactionStatus.completed,
                    )
                    self.session.add(tx)

                    new_sub = Subscription(
                        company_id=sub.company_id,
                        subscription_type=sub.subscription_type,
                        price_usd=sub.price_usd,
                        price_uzs=sub.price_uzs,
                        period_start=now,
                        period_end=now + timedelta(days=30),
                        status=SubscriptionStatus.active,
                        payment_source="balance",
                        auto_renewed=True,
                        paid_at=now,
                    )
                    self.session.add(new_sub)
                    sub.status = SubscriptionStatus.expired
                    await self.session.commit()
                    auto_charged = True

                    users = await self._get_company_users(sub.company_id)
                    msg = (
                        f"✅ <b>Obuna avtomatik yangilandi!</b>\n\n"
                        f"Yangi davr: {now.strftime('%d.%m.%Y')} — "
                        f"{(now + timedelta(days=30)).strftime('%d.%m.%Y')}\n"
                        f"Balansdan yechildi: ${int(price)}"
                    )
                    for user in users:
                        await self._send(user, msg)
                    logger.info("subscription_auto_renewed", company_id=sub.company_id)

            if not auto_charged:
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

    async def _get_director(self, company_id: int):
        result = await self.session.execute(
            select(User)
            .options(selectinload(User.balance))
            .where(
                User.company_id == company_id,
                User.role == UserRole.director,
                User.is_blocked == False,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

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


async def notify_new_user(new_user: User, company: Company, bot, session) -> None:
    """Уведомляет разработчика, директора и всех агентов о новом клиенте."""
    from src.config import settings as cfg

    company_name = company.name if company else "—"
    username = getattr(new_user, "username", None)
    username_text = f"@{username}" if username else "—"

    text = (
        f"🔔 <b>Yangi mijoz!</b>\n\n"
        f"👤 Ism: {new_user.full_name or '—'}\n"
        f"💬 Username: {username_text}\n"
        f"🆔 Telegram ID: <code>{new_user.telegram_user_id}</code>\n"
        f"🏢 Kompaniya: {company_name}"
    )

    staff: list[User] = []
    if company:
        result = await session.execute(
            select(User).where(
                User.company_id == company.id,
                User.role.in_([UserRole.director, UserRole.agent]),
                User.is_blocked == False,
                User.telegram_user_id != 0,
            )
        )
        staff = list(result.scalars())

    recipients: list[int] = []
    developer_id = getattr(cfg, "DEVELOPER_TELEGRAM_ID", None)
    if developer_id:
        recipients.append(developer_id)
    recipients.extend(m.telegram_user_id for m in staff if m.telegram_user_id)
    recipients = list(dict.fromkeys(recipients))

    for chat_id in recipients:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        except Exception as exc:
            logger.warning("notify_new_user_send_failed", chat_id=chat_id, error=str(exc))

    try:
        log = NotificationLog(
            user_id=new_user.id,
            notification_type=NotificationType.new_client,
            related_subscription_id=None,
        )
        session.add(log)
    except Exception as exc:
        logger.warning("notify_new_user_log_failed", user_id=new_user.id, error=str(exc))
