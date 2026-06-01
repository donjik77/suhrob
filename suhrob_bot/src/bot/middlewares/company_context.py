"""
CompanyContextMiddleware — resolves which company owns the incoming update
by looking up the bot's Telegram ID in BotManager's registry.

Injects `company` into handler data. For the developer's personal bot
(no registered company) `company` is None.
"""
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy import func, select

from src.db.session import AsyncSessionFactory
from src.db.models import Company


class CompanyContextMiddleware(BaseMiddleware):
    def __init__(self, bot_manager) -> None:
        self._manager = bot_manager

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot = data.get("bot")
        company: Optional[Company] = None

        if bot is not None:
            company_id = self._manager.get_company_id(bot.id)
            async with AsyncSessionFactory() as session:
                if company_id is not None:
                    company = (
                        await session.execute(
                            select(Company).where(Company.id == company_id)
                        )
                    ).scalar_one_or_none()

                if company is None:
                    company = (
                        await session.execute(
                            select(Company).where(
                                Company.bot_id == bot.id,
                                Company.is_active == True,
                            )
                        )
                    ).scalar_one_or_none()

                if company is None:
                    active_count = await session.scalar(
                        select(func.count(Company.id)).where(Company.is_active == True)
                    )
                    if active_count == 1:
                        company = (
                            await session.execute(
                                select(Company)
                                .where(Company.is_active == True)
                                .order_by(Company.id.asc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()

                if company is not None and hasattr(self._manager, "_bot_to_company"):
                    self._manager._bot_to_company[bot.id] = company.id

        data["company"] = company
        return await handler(event, data)
