from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery

from src.db.session import AsyncSessionFactory
from src.db.repositories.user_repo import UserRepository
from src.db.models import UserRole
from src.config import settings


class AuthMiddleware(BaseMiddleware):
    """Resolves the current user from telegram_user_id and injects into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = None

        if isinstance(event, (Message, CallbackQuery)):
            tg_user = event.from_user
        elif isinstance(event, Update):
            if event.message:
                tg_user = event.message.from_user
            elif event.callback_query:
                tg_user = event.callback_query.from_user

        if tg_user is None:
            return await handler(event, data)

        async with AsyncSessionFactory() as session:
            repo = UserRepository(session)
            user, is_new = await repo.get_or_create(
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name,
            )

            if not is_new:
                await repo.update_last_active(tg_user.id)

            # Ensure developer always has developer role
            if tg_user.id == settings.DEVELOPER_TELEGRAM_ID and user.role != UserRole.developer:
                from sqlalchemy import update
                from src.db.models import User
                await session.execute(
                    update(User)
                    .where(User.telegram_user_id == tg_user.id)
                    .values(role=UserRole.developer)
                )
                await session.commit()
                await session.refresh(user)

            data["db_user"] = user
            data["db_session"] = session

        return await handler(event, data)
