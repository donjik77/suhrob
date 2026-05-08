import asyncio
import logging
import os

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from src.config import settings
from src.bot.manager import BotManager
from src.bot.middlewares.auth import AuthMiddleware
from src.bot.middlewares.company_context import CompanyContextMiddleware
from src.bot.middlewares.subscription import SubscriptionMiddleware
from src.bot.middlewares.logging import LoggingMiddleware

# Handlers
from src.bot.handlers.common import router as common_router
from src.bot.handlers.client.search import router as search_router
from src.bot.handlers.client.favorites import router as favorites_router
from src.bot.handlers.client.start import router as client_start_router
from src.bot.handlers.client.ai_consultation import router as ai_consult_router
from src.bot.handlers.client.alerts import router as alerts_router
from src.bot.handlers.client.mortgage import router as mortgage_router
from src.bot.handlers.agent.add_property import router as add_property_router
from src.bot.handlers.agent.my_properties import router as my_properties_router
from src.bot.handlers.agent.my_clients import router as my_clients_router
from src.bot.handlers.agent.scheduled_posts import router as scheduled_posts_router
from src.bot.handlers.agent.stats import router as agent_stats_router
from src.bot.handlers.agent.agent_settings import router as agent_settings_router
from src.bot.handlers.agent.instagram import router as instagram_router
from src.bot.handlers.shared.profile import router as shared_profile_router
from src.bot.handlers.director.agents import router as director_agents_router
from src.bot.handlers.director.subscription import router as subscription_router
from src.bot.handlers.director.properties import router as director_properties_router
from src.bot.handlers.director.profile import router as director_profile_router
from src.bot.handlers.director.balance import router as director_balance_router
from src.bot.handlers.director.dashboard import router as dashboard_router
from src.bot.handlers.developer.payments import router as dev_payments_router
from src.bot.handlers.developer.settings import router as dev_settings_router
from src.bot.handlers.developer.companies import router as dev_companies_router

from src.scheduler.setup import setup_scheduler


async def auto_register_preset_users() -> None:
    """Register director and agents from .env on every startup (idempotent)."""
    from sqlalchemy import select
    from sqlalchemy import update as sa_update
    from src.db.session import AsyncSessionFactory
    from src.db.models import Company, User, UserRole as UR

    preset = [
        (settings.DIRECTOR_TELEGRAM_ID, UR.director),
        (settings.AGENT_1_TELEGRAM_ID, UR.agent),
        (settings.AGENT_2_TELEGRAM_ID, UR.agent),
        (settings.AGENT_3_TELEGRAM_ID, UR.agent),
    ]
    preset = [(tg_id, role) for tg_id, role in preset if tg_id]
    if not preset:
        return

    async with AsyncSessionFactory() as session:
        company = (await session.execute(
            select(Company).where(Company.is_active == True).limit(1)
        )).scalar_one_or_none()
        company_id = company.id if company else None

        for tg_id, role in preset:
            if tg_id == settings.DEVELOPER_TELEGRAM_ID:
                continue
            existing = (await session.execute(
                select(User).where(User.telegram_user_id == tg_id)
            )).scalar_one_or_none()
            if existing:
                updates: dict = {}
                if existing.role != role:
                    updates["role"] = role
                if company_id and existing.company_id != company_id:
                    updates["company_id"] = company_id
                if updates:
                    await session.execute(
                        sa_update(User).where(User.telegram_user_id == tg_id).values(**updates)
                    )
            else:
                session.add(User(telegram_user_id=tg_id, role=role, company_id=company_id))

        await session.commit()
    logging.info("auto_register_preset_users: completed")


def run_migrations() -> None:
    """Run alembic upgrade head before the event loop starts."""
    try:
        from alembic.config import Config
        from alembic import command as alembic_command

        ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini")
        if not os.path.exists(ini_path):
            logging.warning("alembic.ini not found at %s — skipping auto-migration", ini_path)
            return
        cfg = Config(ini_path)
        alembic_command.upgrade(cfg, "head")
        logging.info("alembic upgrade head: OK")
    except Exception as exc:
        logging.error("alembic upgrade head failed: %s", exc)
        raise


def setup_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    )


def build_dispatcher(storage) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    return dp


def register_routers(dp: Dispatcher) -> None:
    # Order matters: more specific routes first
    dp.include_router(common_router)
    dp.include_router(search_router)
    dp.include_router(favorites_router)
    dp.include_router(client_start_router)
    dp.include_router(ai_consult_router)
    dp.include_router(alerts_router)
    dp.include_router(mortgage_router)
    dp.include_router(add_property_router)
    dp.include_router(my_properties_router)
    dp.include_router(my_clients_router)
    dp.include_router(scheduled_posts_router)
    dp.include_router(agent_stats_router)
    dp.include_router(agent_settings_router)
    dp.include_router(instagram_router)
    dp.include_router(shared_profile_router)
    dp.include_router(director_agents_router)
    dp.include_router(director_properties_router)
    dp.include_router(director_profile_router)
    dp.include_router(director_balance_router)
    dp.include_router(dashboard_router)
    dp.include_router(subscription_router)
    dp.include_router(dev_payments_router)
    dp.include_router(dev_settings_router)
    dp.include_router(dev_companies_router)


async def main():
    setup_logging()
    logger = structlog.get_logger()
    logger.info("bot_platform_starting", name=settings.BOT_NAME)

    storage = RedisStorage.from_url(settings.REDIS_URL)
    dp = build_dispatcher(storage)

    # Build BotManager (manages all company bots)
    bot_manager = BotManager(dp)

    # Middlewares (order matters — company context before auth)
    dp.update.outer_middleware(LoggingMiddleware())
    dp.update.outer_middleware(CompanyContextMiddleware(bot_manager))
    dp.update.outer_middleware(AuthMiddleware())
    dp.update.outer_middleware(SubscriptionMiddleware())

    register_routers(dp)

    # Developer's own bot (uses DEVELOPER_TELEGRAM_ID, no company)
    # This bot token must still be set — use any single company bot token or a dedicated dev bot
    # For single-company setups, set BOT_TOKEN in .env as a fallback.
    dev_bot_token = None
    try:
        from src.config import settings as s
        import os
        dev_bot_token = os.environ.get("BOT_TOKEN") or None
    except Exception:
        pass

    # Auto-register preset director/agents from .env
    await auto_register_preset_users()

    # Start all company bots from DB
    await bot_manager.start_all()

    # If a fallback BOT_TOKEN is set and no bots loaded, run it for dev/initial setup
    if bot_manager.running_count() == 0 and dev_bot_token:
        logger.warning("no_company_bots_found", message="Starting with fallback BOT_TOKEN for initial setup")
        dev_bot = Bot(
            token=dev_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        scheduler = setup_scheduler(dev_bot)
        scheduler.start()
        logger.info("fallback_bot_started")
        try:
            await dp.start_polling(dev_bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            scheduler.shutdown()
            await dev_bot.session.close()
    else:
        # Pick one bot for scheduler (first active company bot)
        scheduler_bot = None
        if bot_manager._bots:
            scheduler_bot = next(iter(bot_manager._bots.values()))
        if scheduler_bot:
            scheduler = setup_scheduler(scheduler_bot)
            scheduler.start()

        logger.info("bot_platform_started", count=bot_manager.running_count())
        try:
            # Keep running until cancelled
            await asyncio.Event().wait()
        finally:
            if scheduler_bot:
                scheduler.shutdown()
            await bot_manager.stop_all()

    logger.info("bot_platform_stopped")


if __name__ == "__main__":
    run_migrations()
    asyncio.run(main())
