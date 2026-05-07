"""
CompanyContextMiddleware — resolves which company owns the incoming update
by looking up the bot's Telegram ID in BotManager's registry.

Injects `company` into handler data. For the developer's personal bot
(no registered company) `company` is None.
"""
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery

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
            if company_id is not None:
                async with AsyncSessionFactory() as session:
                    from sqlalchemy import select
                    from sqlalchemy.orm import selectinload
                    company = (
                        await session.execute(
                            select(Company)
                            .where(Company.id == company_id)
                        )
                    ).scalar_one_or_none()

        data["company"] = company
        return await handler(event, data)
