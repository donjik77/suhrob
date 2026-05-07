from datetime import datetime

import structlog
from aiogram import Bot

from src.db.session import AsyncSessionFactory
from src.services.notification_service import NotificationService

logger = structlog.get_logger()


async def job_check_reminders(bot: Bot) -> None:
    logger.info("scheduler_job_start", job="check_reminders")
    async with AsyncSessionFactory() as session:
        svc = NotificationService(session, bot)
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
    now = datetime.utcnow()

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import ScheduledPost, ScheduledPostStatus
        from src.services.publisher_service import PublisherService

        result = await session.execute(
            select(ScheduledPost).where(
                ScheduledPost.status == ScheduledPostStatus.pending,
                ScheduledPost.scheduled_at <= now,
            )
        )
        posts = list(result.scalars().all())

        for post in posts:
            publisher = PublisherService(session, bot)
            success, msg = await publisher.publish(post.property_id)

            if success:
                post.status = ScheduledPostStatus.published
                post.published_at = now
            else:
                post.status = ScheduledPostStatus.failed
                post.error_message = msg

        await session.commit()

    logger.info("scheduler_job_done", job="publish_scheduled_posts", count=len(posts))
