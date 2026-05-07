import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from src.config import settings
from src.bot.middlewares.auth import AuthMiddleware
from src.bot.middlewares.subscription import SubscriptionMiddleware
from src.bot.middlewares.logging import LoggingMiddleware

from src.bot.handlers.common import router as common_router
from src.bot.handlers.client.search import router as search_router
from src.bot.handlers.client.favorites import router as favorites_router
from src.bot.handlers.client.start import router as client_start_router
from src.bot.handlers.agent.add_property import router as add_property_router
from src.bot.handlers.agent.my_properties import router as my_properties_router
from src.bot.handlers.agent.stats import router as agent_stats_router
from src.bot.handlers.director.agents import router as director_agents_router
from src.bot.handlers.director.subscription import router as subscription_router
from src.bot.handlers.developer.payments import router as dev_payments_router
from src.bot.handlers.developer.settings import router as dev_settings_router

from src.scheduler.setup import setup_scheduler


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


async def main():
    setup_logging()
    logger = structlog.get_logger()
    logger.info("bot_starting", bot_name=settings.BOT_NAME)

    storage = RedisStorage.from_url(settings.REDIS_URL)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=storage)

    # Middlewares (order matters)
    dp.update.outer_middleware(LoggingMiddleware())
    dp.update.outer_middleware(AuthMiddleware())
    dp.update.outer_middleware(SubscriptionMiddleware())

    # Routers — order matters for priority
    dp.include_router(common_router)
    dp.include_router(search_router)
    dp.include_router(favorites_router)
    dp.include_router(client_start_router)
    dp.include_router(add_property_router)
    dp.include_router(my_properties_router)
    dp.include_router(agent_stats_router)
    dp.include_router(director_agents_router)
    dp.include_router(subscription_router)
    dp.include_router(dev_payments_router)
    dp.include_router(dev_settings_router)

    # Scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()

    logger.info("bot_started", polling=True)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("bot_stopped")


if __name__ == "__main__":
    asyncio.run(main())
