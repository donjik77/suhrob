from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery

from src.db.session import AsyncSessionFactory
from src.db.repositories.user_repo import UserRepository
from src.db.models import UserRole
from src.config import settings


def _expected_role(tg_id: int) -> Optional[UserRole]:
    if tg_id == settings.DEVELOPER_TELEGRAM_ID:
        return UserRole.developer
    if tg_id == settings.DIRECTOR_TELEGRAM_ID:
        return UserRole.director
    if tg_id in settings.AGENT_TELEGRAM_IDS:
        return UserRole.agent
    return None


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

            expected = _expected_role(tg_user.id)

            if expected and (is_new or user.role != expected):
                from sqlalchemy import update, select
                from src.db.models import User, Company

                updates: dict = {"role": expected}

                # Assign company for director/agent if not yet set
                if expected in (UserRole.director, UserRole.agent) and not user.company_id:
                    company = (
                        await session.execute(select(Company).limit(1))
                    ).scalar_one_or_none()
                    if company:
                        updates["company_id"] = company.id

                await session.execute(
                    update(User)
                    .where(User.telegram_user_id == tg_user.id)
                    .values(**updates)
                )
                await session.commit()
                await session.refresh(user)
            elif not is_new:
                await repo.update_last_active(tg_user.id)

            data["db_user"] = user
            data["db_session"] = session

        return await handler(event, data)
