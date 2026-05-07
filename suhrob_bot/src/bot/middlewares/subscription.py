from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from src.db.models import UserRole, User
from src.db.repositories.subscription_repo import SubscriptionRepository
from locales.uz import t


class SubscriptionMiddleware(BaseMiddleware):
    """
    Blocks non-developer users when the company subscription is expired or blocked.
    Must run after AuthMiddleware (requires data['db_user'] and data['db_session']).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("db_user")

        if user is None:
            return await handler(event, data)

        # Developer is never blocked
        if user.role == UserRole.developer:
            return await handler(event, data)

        # Clients without a company — allow through (they see public info)
        if user.company_id is None:
            return await handler(event, data)

        session = data.get("db_session")
        if session is None:
            return await handler(event, data)

        repo = SubscriptionRepository(session)
        blocked = await repo.is_blocked(user.company_id)

        if blocked:
            if isinstance(event, (Message, CallbackQuery)):
                if user.role == UserRole.client:
                    msg = t("service_blocked_client")
                else:
                    msg = t("service_blocked_agent")

                if isinstance(event, Message):
                    await event.answer(msg)
                elif isinstance(event, CallbackQuery):
                    await event.answer(msg, show_alert=True)
            return  # Stop processing

        return await handler(event, data)
