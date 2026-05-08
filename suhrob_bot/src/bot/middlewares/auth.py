"""
AuthMiddleware — resolves the current user from telegram_user_id.

Role logic:
  - DEVELOPER_TELEGRAM_ID in config → always developer, never blocked
  - All other users: role is stored in the users table (set by director or init script)
  - New users default to client; their company_id comes from the company that owns
    the bot they're talking to (injected by CompanyContextMiddleware as `company`)
"""
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update, Message, CallbackQuery
from sqlalchemy import update as sa_update

from src.db.session import AsyncSessionFactory
from src.db.models import User, UserRole, Company
from src.config import settings


class AuthMiddleware(BaseMiddleware):
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

        company: Optional[Company] = data.get("company")

        async with AsyncSessionFactory() as session:
            from src.db.repositories.user_repo import UserRepository
            repo = UserRepository(session)

            user, is_new = await repo.get_or_create(
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name,
                company_id=company.id if company else None,
            )

            if tg_user.id == settings.DEVELOPER_TELEGRAM_ID:
                # Developer is hardcoded — ensure role is correct
                if user.role != UserRole.developer:
                    await session.execute(
                        sa_update(User)
                        .where(User.telegram_user_id == tg_user.id)
                        .values(role=UserRole.developer)
                    )
                    await session.commit()
                    await session.refresh(user)
            else:
                if not is_new:
                    # Attach company if user somehow has none and a company is known
                    if user.company_id is None and company is not None:
                        await session.execute(
                            sa_update(User)
                            .where(User.telegram_user_id == tg_user.id)
                            .values(company_id=company.id)
                        )
                        await session.commit()
                        await session.refresh(user)
                    await repo.update_last_active(tg_user.id)

            data["db_user"] = user
            data["db_session"] = session

            return await handler(event, data)
