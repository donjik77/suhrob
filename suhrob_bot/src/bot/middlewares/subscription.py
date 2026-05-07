from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from src.db.models import UserRole, User
from src.db.repositories.subscription_repo import SubscriptionRepository
from locales.uz import t


class SubscriptionMiddleware(BaseMiddleware):
    """
    Blocks non-developer users when the company subscription is expired/blocked.
    When there is no active subscription at all, blocks clients too.
    Must run after AuthMiddleware.
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

        if user.role == UserRole.developer:
            return await handler(event, data)

        session = data.get("db_session")
        if session is None:
            return await handler(event, data)

        repo = SubscriptionRepository(session)

        if user.company_id:
            blocked = await repo.is_blocked(user.company_id)
        else:
            # Client has no company — block if there is no active subscription anywhere
            blocked = await repo.is_service_blocked()

        if blocked:
            if isinstance(event, (Message, CallbackQuery)):
                msg = (
                    t("service_blocked_client")
                    if user.role == UserRole.client
                    else t("service_blocked_agent")
                )
                if isinstance(event, Message):
                    await event.answer(msg)
                else:
                    await event.answer(msg, show_alert=True)
            return

        return await handler(event, data)
