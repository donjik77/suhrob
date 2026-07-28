from datetime import datetime

import structlog
from aiogram import Bot
from sqlalchemy import select

from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService

logger = structlog.get_logger()


# ------------------------------------------------------------------ #
#  Отправка клиенту с учётом канала
# ------------------------------------------------------------------ #
#
# Instagram-клиенты лежат в users с ОТРИЦАТЕЛЬНЫМ telegram_user_id
# (-abs(salebot_client_id)) — так сделано в мосте, чтобы не путать их с
# реальными Telegram id. Раньше все джобы звали bot.send_message() с этим
# отрицательным id: Telegram Bot API такой chat не находит, вызов падал в
# except и тихо логировался как follow_up_send_failed. То есть механизм
# напоминаний в принципе не мог достучаться до Instagram.
#
# Инлайн-кнопок в Instagram нет, поэтому там используются reply-кнопки
# Salebot — тот же параметр buttons, что и в обычных ответах моста.
#
# job_check_reminders сюда НЕ входит: он уведомляет об окончании подписки
# директоров и агентов, а это всегда реальные Telegram-пользователи.

def is_instagram_client(user) -> bool:
    return (user.telegram_user_id or 0) < 0


async def send_to_client(bot: Bot, user, text: str,
                         buttons: list[str] | None = None,
                         reply_markup=None, parse_mode: str | None = None,
                         sendpulse_contact_id: str | None = None) -> bool:
    """
    Шлёт сообщение клиенту в его канал.

    sendpulse_contact_id — оригинальный SendPulse contact_id клиента
    (ClientProfile.sendpulse_contact_id), обязателен для Instagram-веток:
    user.telegram_user_id для них — необратимый хеш этого ID (см.
    instagram_bridge.smmbot_webhook), восстановить его нельзя.
    Salebot (send_salebot_message) больше не вызывается — тот канал
    отключён, оставлен только как мёртвый код на /webhook/instagram.

    buttons сейчас не используется для Instagram: SendPulse
    /instagram/contacts/send поддерживает только text/image, без кнопок.
    reply_markup — инлайн-клавиатура для Telegram.
    """
    if is_instagram_client(user):
        if not sendpulse_contact_id:
            logger.warning("send_to_client_no_sendpulse_contact", user_id=user.id)
            return False
        from src.services.sendpulse_client import send_sendpulse_message
        return await send_sendpulse_message(sendpulse_contact_id, text)

    kwargs = {}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    await bot.send_message(user.telegram_user_id, text, **kwargs)
    return True


async def job_check_reminders(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="check_reminders")
    async with AsyncSessionFactory() as session:
        svc = NotificationService(session, bot)
        await svc.send_7day_reminders()
        await svc.send_3day_reminders()
    logger.info("scheduler_job_done", job="check_reminders")


async def job_expire_subscriptions(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="expire_subscriptions")
    async with AsyncSessionFactory() as session:
        svc = NotificationService(session, bot)
        await svc.expire_subscriptions()
    logger.info("scheduler_job_done", job="expire_subscriptions")


async def job_publish_scheduled_posts(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="publish_scheduled_posts")
    from src.db.models import ScheduledPost, ScheduledPostStatus
    from src.services.publisher_service import PublisherService

    # Phase 1: atomically claim pending posts by marking them in_progress.
    # FOR UPDATE SKIP LOCKED prevents duplicate processing on concurrent/restarted workers.
    async with AsyncSessionFactory() as session:
        async with session.begin():
            stmt = (
                select(ScheduledPost)
                .where(
                    ScheduledPost.status == ScheduledPostStatus.pending,
                    ScheduledPost.scheduled_at <= datetime.utcnow(),
                )
                .with_for_update(skip_locked=True)
                .limit(10)
            )
            result = await session.execute(stmt)
            posts = list(result.scalars())

            for post in posts:
                post.status = ScheduledPostStatus.in_progress
            # commit happens on context manager exit

    if not posts:
        logger.info("scheduler_job_done", job="publish_scheduled_posts", count=0)
        return

    # Phase 2: publish each claimed post and update final status.
    for post in posts:
        try:
            async with AsyncSessionFactory() as s2:
                publisher = PublisherService(session=s2, bot=bot)
                success, msg = await publisher.publish(post.property_id)
                p = await s2.get(ScheduledPost, post.id)
                if p is None:
                    logger.warning("scheduled_post_missing_after_publish", post_id=post.id)
                    continue
                if success:
                    p.status = ScheduledPostStatus.published
                    p.published_at = datetime.utcnow()
                else:
                    p.status = ScheduledPostStatus.failed
                    p.error_message = (msg or "")[:500]
                await s2.commit()
        except Exception as e:
            async with AsyncSessionFactory() as s2:
                p = await s2.get(ScheduledPost, post.id)
                if p is not None:
                    p.status = ScheduledPostStatus.failed
                    p.error_message = str(e)[:500]
                    await s2.commit()
            logger.error("publish_scheduled_post_failed", post_id=post.id, error=str(e))

    logger.info("scheduler_job_done", job="publish_scheduled_posts", count=len(posts))


async def job_send_follow_ups(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="send_follow_ups")
    from datetime import timezone
    from sqlalchemy import select
    from src.db.models import ClientProfile, User

    async with AsyncSessionFactory() as session:
        now = datetime.now(timezone.utc)

        # Load all non-unsubscribed profiles with last_contact_at set
        result = await session.execute(
            select(ClientProfile, User)
            .join(User, User.id == ClientProfile.user_id)
            .where(
                ClientProfile.unsubscribed == False,
                ClientProfile.last_contact_at != None,
            )
        )
        rows = list(result.all())

        from locales.uz import t

        for profile, user in rows:
            days_since = (now - profile.last_contact_at.replace(tzinfo=timezone.utc)).days
            count = profile.follow_up_count
            name = user.full_name or user.username or "Do'stim"
            district = (profile.preferred_districts or [""])[0] if profile.preferred_districts else "tanlangan"
            budget = f"{int(profile.budget_max_usd):,}" if profile.budget_max_usd else "?"

            msg = None
            if count == 0 and days_since >= 3:
                msg = t("follow_up_day3", name=name, district=district)
                profile.follow_up_count = 1
            elif count == 1 and days_since >= 7:
                msg = t("follow_up_day7", name=name, budget=budget)
                profile.follow_up_count = 2
            elif count == 2 and days_since >= 14:
                msg = t("follow_up_day14", name=name)
                profile.follow_up_count = 3
                profile.unsubscribed = True

            if msg:
                try:
                    from aiogram.utils.keyboard import InlineKeyboardBuilder
                    builder = InlineKeyboardBuilder()
                    if count == 0:
                        labels = [t("btn_follow_up_yes"), t("btn_follow_up_no"),
                                  t("btn_follow_up_unsub")]
                        builder.button(text=labels[0], callback_data="followup:yes")
                        builder.button(text=labels[1], callback_data="followup:no")
                        builder.button(text=labels[2], callback_data="followup:unsub")
                        builder.adjust(2, 1)
                    else:
                        labels = [t("btn_follow_up_looking"), t("btn_follow_up_found")]
                        builder.button(text=labels[0], callback_data="followup:yes")
                        builder.button(text=labels[1], callback_data="followup:found")
                        builder.adjust(2)

                    # В Instagram кнопок нет (SendPulse API их не поддерживает
                    # для этого типа сообщения) — уйдёт только текст.
                    sent = await send_to_client(
                        bot, user, msg,
                        buttons=labels,
                        reply_markup=builder.as_markup(),
                        sendpulse_contact_id=profile.sendpulse_contact_id,
                    )
                    logger.info("follow_up_sent", user_id=user.id, day=count,
                                channel="instagram" if is_instagram_client(user)
                                else "telegram", sent=sent)
                except Exception as exc:
                    logger.warning("follow_up_send_failed", user_id=user.id,
                                   channel="instagram" if is_instagram_client(user)
                                   else "telegram", error=str(exc))

        await session.commit()
    logger.info("scheduler_job_done", job="send_follow_ups")


async def job_cleanup_old_notifications(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="cleanup_notifications")
    from datetime import timezone, timedelta
    from sqlalchemy import delete
    from src.db.models import NotificationLog

    async with AsyncSessionFactory() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        await session.execute(
            delete(NotificationLog).where(NotificationLog.sent_at < cutoff)
        )
        await session.commit()
    logger.info("scheduler_job_done", job="cleanup_notifications")


async def job_send_property_alerts(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="send_property_alerts")
    from datetime import timezone, timedelta
    from sqlalchemy import select, and_
    from sqlalchemy.orm import selectinload
    from src.db.models import ClientAlert, Property, PropertyStatus, PropertyType, User

    async with AsyncSessionFactory() as session:
        now = datetime.now(timezone.utc)
        lookback = now - timedelta(hours=24)

        # Get all active alerts
        alerts_result = await session.execute(
            select(ClientAlert, User)
            .join(User, User.id == ClientAlert.user_id)
            .where(ClientAlert.is_active == True)
        )
        rows = list(alerts_result.all())

        sent_count = 0
        for alert, user in rows:
            # Only check properties newer than last_notified_at (or 24h ago)
            since = alert.last_notified_at.replace(tzinfo=timezone.utc) if alert.last_notified_at else lookback

            conditions = [
                Property.status == PropertyStatus.active,
                Property.created_at > since,
                Property.company_id == user.company_id,
            ]
            if alert.location_district:
                conditions.append(Property.location_district == alert.location_district)
            if alert.price_max_usd:
                conditions.append(Property.price_usd <= alert.price_max_usd)
            if alert.rooms:
                conditions.append(Property.rooms == alert.rooms)
            if alert.property_type:
                conditions.append(Property.property_type == alert.property_type)

            props_result = await session.execute(
                select(Property)
                .options(selectinload(Property.media))
                .where(and_(*conditions))
                .limit(3)
            )
            props = list(props_result.scalars().all())

            if not props:
                continue

            from src.db.repositories.settings_repo import SettingsRepository
            from src.utils.formatters import format_property_card
            from src.bot.keyboards.client import property_card_kb
            from src.bot.utils.property_media import send_property_media_card

            settings_repo = SettingsRepository(session)
            rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

            try:
                if is_instagram_client(user):
                    # В Instagram карточек нет — короткий текстовый список,
                    # фото клиент попросит сам (как в обычном диалоге).
                    from src.db.models import ClientProfile
                    from src.services.sendpulse_client import send_sendpulse_message

                    profile = (
                        await session.execute(
                            select(ClientProfile).where(ClientProfile.user_id == user.id)
                        )
                    ).scalar_one_or_none()
                    contact_id = profile.sendpulse_contact_id if profile else None
                    if not contact_id:
                        logger.warning("alert_no_sendpulse_contact", user_id=user.id)
                        continue

                    from src.services.ai_service import normalize_price_usd

                    lines = ["Yangi mos variantlar:"]
                    for prop in props:
                        price = f"{normalize_price_usd(prop.price_usd):,.0f}".replace(",", " ")
                        lines.append(
                            f"{prop.location_district}, {prop.rooms} xona, ${price}"
                        )
                    lines.append("Rasmlarini ko'rasizmi?")
                    await send_sendpulse_message(contact_id, "\n".join(lines))
                else:
                    await bot.send_message(
                        user.telegram_user_id,
                        "🔔 <b>Yangi mos variantlar!</b>\n\nSizning qidiruvingizga mos yangi uylar chiqdi:",
                        parse_mode="HTML",
                    )
                    for prop in props:
                        caption = format_property_card(prop, rate)
                        await send_property_media_card(
                            bot,
                            chat_id=user.telegram_user_id,
                            media_items=prop.media,
                            caption=caption,
                            reply_markup=property_card_kb(prop.id),
                            parse_mode="HTML",
                            caption_entities_json=prop.custom_text_entities_json if prop.custom_text else None,
                        )
                sent_count += 1
            except Exception as exc:
                logger.warning("alert_send_failed", user_id=user.id,
                               channel="instagram" if is_instagram_client(user)
                               else "telegram", error=str(exc))
                continue

            alert.last_notified_at = now

        await session.commit()

    logger.info("scheduler_job_done", job="send_property_alerts", sent=sent_count)
