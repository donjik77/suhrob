from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from src.config import settings


def setup_scheduler(bot) -> AsyncIOScheduler:
    tz = pytz.timezone(settings.TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz)

    from src.scheduler.jobs import (
        job_check_reminders,
        job_expire_subscriptions,
        job_publish_scheduled_posts,
    )

    # Check for 3-day reminders every hour
    scheduler.add_job(
        job_check_reminders,
        trigger=CronTrigger(minute=0),
        kwargs={"bot": bot},
        id="check_reminders",
        replace_existing=True,
    )

    # Check for expired subscriptions every hour
    scheduler.add_job(
        job_expire_subscriptions,
        trigger=CronTrigger(minute=5),
        kwargs={"bot": bot},
        id="expire_subscriptions",
        replace_existing=True,
    )

    # Publish scheduled posts every 5 minutes
    scheduler.add_job(
        job_publish_scheduled_posts,
        trigger=CronTrigger(minute="*/5"),
        kwargs={"bot": bot},
        id="publish_scheduled_posts",
        replace_existing=True,
    )

    return scheduler
