"""
BotManager — runs one aiogram Bot per company on the same event loop.
New bots can be added at runtime without restarting the process.
"""
import asyncio
import structlog
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.db.session import AsyncSessionFactory
from src.db.models import Company

logger = structlog.get_logger()


class BotManager:
    def __init__(self, dp: Dispatcher):
        self._dp = dp
        # company_id -> Bot
        self._bots: dict[int, Bot] = {}
        # bot_id -> company_id  (fast lookup for CompanyContextMiddleware)
        self._bot_to_company: dict[int, int] = {}

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _make_bot(self, token: str) -> Bot:
        return Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    async def _start_polling(self, bot: Bot) -> None:
        try:
            await self._dp.start_polling(
                bot,
                allowed_updates=self._dp.resolve_used_update_types(),
                close_bot_session=False,
            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("bot_polling_error", bot_id=bot.id, error=str(exc))

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    async def add_bot(self, token: str, company_id: int) -> None:
        if company_id in self._bots:
            logger.warning("bot_already_running", company_id=company_id)
            return
        bot = self._make_bot(token)
        bot_info = await bot.get_me()
        self._bots[company_id] = bot
        self._bot_to_company[bot_info.id] = company_id
        asyncio.create_task(self._start_polling(bot))
        logger.info("bot_added", company_id=company_id, bot_username=bot_info.username)

        if bot_info.id or bot_info.username:
            from sqlalchemy import update
            async with AsyncSessionFactory() as session:
                try:
                    await session.execute(
                        update(Company)
                        .where(Company.id == company_id)
                        .values(bot_id=bot_info.id, bot_username=bot_info.username)
                    )
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    logger.warning(
                        "bot_metadata_update_failed",
                        company_id=company_id,
                        bot_id=bot_info.id,
                        error=str(exc),
                    )

    async def remove_bot(self, company_id: int) -> None:
        bot = self._bots.pop(company_id, None)
        if bot is None:
            return
        bot_info = await bot.get_me()
        self._bot_to_company.pop(bot_info.id, None)
        await bot.session.close()
        logger.info("bot_removed", company_id=company_id)

    async def start_all(self) -> None:
        """Load all active companies from DB and start their bots."""
        async with AsyncSessionFactory() as session:
            from sqlalchemy import select
            rows = (
                await session.execute(
                    select(Company).where(Company.is_active == True, Company.bot_token != None)
                )
            ).scalars().all()

        for company in rows:
            if company.bot_token:
                await self.add_bot(company.bot_token, company.id)

        logger.info("bot_manager_started", count=len(self._bots))

    async def stop_all(self) -> None:
        for company_id in list(self._bots.keys()):
            await self.remove_bot(company_id)

    def get_company_id(self, bot_id: int) -> Optional[int]:
        return self._bot_to_company.get(bot_id)

    def remember_company_bot(self, bot_id: int, company_id: int) -> None:
        self._bot_to_company[bot_id] = company_id

    def running_count(self) -> int:
        return len(self._bots)
