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
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.orm import selectinload

from src.db.session import AsyncSessionFactory
from src.db.models import User, UserRole, Company
from src.config import settings


class AuthMiddleware(BaseMiddleware):
    def _preset_role_for_telegram_id(self, telegram_id: int) -> Optional[UserRole]:
        if getattr(settings, "DIRECTOR_TELEGRAM_ID", None) == telegram_id:
            return UserRole.director

        agent_ids = (
            getattr(settings, "AGENT_1_TELEGRAM_ID", None),
            getattr(settings, "AGENT_2_TELEGRAM_ID", None),
            getattr(settings, "AGENT_3_TELEGRAM_ID", None),
        )
        if telegram_id in [agent_id for agent_id in agent_ids if agent_id]:
            return UserRole.agent

        return None

    async def _get_user_without_company_context(self, session, repo, telegram_id: int) -> Optional[User]:
        scoped_users = (
            await session.execute(
                select(User)
                .where(
                    User.telegram_user_id == telegram_id,
                    User.company_id.is_not(None),
                )
                .options(selectinload(User.company))
                .order_by(User.id.desc())
            )
        ).scalars().all()

        employees = [
            user for user in scoped_users
            if user.role in (UserRole.director, UserRole.agent)
        ]
        if len(employees) == 1:
            return employees[0]

        global_user = await repo.get_by_telegram_id(telegram_id, company_id=None)
        if global_user:
            return global_user

        if len(scoped_users) == 1:
            return scoped_users[0]

        return None

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

            company_id = company.id if company else None

            if tg_user.id == settings.DEVELOPER_TELEGRAM_ID:
                # Developer is hardcoded and global, never scoped to a company bot.
                user = await repo.get_by_telegram_id(tg_user.id, company_id=None)
                if user is None:
                    user = await repo.get_by_telegram_id(tg_user.id, any_company=True)
                    if user is None:
                        user = await repo.create(
                            telegram_id=tg_user.id,
                            username=tg_user.username,
                            full_name=tg_user.full_name,
                            role=UserRole.developer,
                            company_id=None,
                        )
                    elif user.company_id is not None or user.role != UserRole.developer:
                        user.company_id = None
                        user.role = UserRole.developer
                        await session.commit()
                        await session.refresh(user)
                elif user.role != UserRole.developer:
                    await session.execute(
                        sa_update(User)
                        .where(User.id == user.id)
                        .values(role=UserRole.developer, username=tg_user.username, full_name=tg_user.full_name)
                    )
                    await session.commit()
                    await session.refresh(user)
            else:
                preset_role = self._preset_role_for_telegram_id(tg_user.id)

                if company_id is None:
                    user = await self._get_user_without_company_context(session, repo, tg_user.id)
                else:
                    user = await repo.get_by_telegram_id(tg_user.id, company_id=company_id)

                pending_agent = None
                if company_id is not None and tg_user.username:
                    pending_agent = await repo.get_pending_agent_by_username(tg_user.username, company_id)

                if pending_agent and user and pending_agent.id != user.id:
                    # The person first used the bot as a client, then was invited by username.
                    user.role = pending_agent.role
                    user.phone = pending_agent.phone or user.phone
                    user.full_name = pending_agent.full_name or tg_user.full_name
                    user.username = tg_user.username
                    await session.delete(pending_agent)
                    await session.commit()
                    await session.refresh(user)
                elif pending_agent and user is None:
                    pending_agent.telegram_user_id = tg_user.id
                    pending_agent.username = tg_user.username
                    pending_agent.full_name = pending_agent.full_name or tg_user.full_name
                    await session.commit()
                    await session.refresh(pending_agent)
                    user = pending_agent

                if user is None and company_id is not None:
                    legacy_user = await repo.get_by_telegram_id(tg_user.id, company_id=None)
                    if legacy_user and legacy_user.role == UserRole.client:
                        legacy_user.company_id = company_id
                        legacy_user.username = tg_user.username
                        legacy_user.full_name = tg_user.full_name
                        await session.commit()
                        await session.refresh(legacy_user)
                        user = legacy_user

                if user is None:
                    user = await repo.create(
                        telegram_id=tg_user.id,
                        username=tg_user.username,
                        full_name=tg_user.full_name,
                        role=preset_role if company_id is not None else UserRole.client,
                        company_id=company_id,
                    )
                else:
                    if (
                        preset_role is not None
                        and company_id is not None
                        and user.company_id == company_id
                        and user.role != preset_role
                    ):
                        user.role = preset_role
                    await session.execute(
                        sa_update(User)
                        .where(User.id == user.id)
                        .values(
                            username=tg_user.username,
                            full_name=user.full_name or tg_user.full_name,
                            last_active_at=func.now(),
                        )
                    )
                    await session.commit()
                    await session.refresh(user)

            # Blocked users cannot use the bot (developer is never blocked)
            if user.is_blocked and user.role != UserRole.developer:
                if isinstance(event, Message):
                    await event.answer("🔒 Sizning hisobingiz bloklangan. Administrator bilan bog'laning.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🔒 Hisob bloklangan", show_alert=True)
                return

            data["db_user"] = user
            data["db_session"] = session

            return await handler(event, data)
