from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(
        self,
        telegram_id: int,
        company_id: Optional[int] = None,
        *,
        any_company: bool = False,
    ) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.telegram_user_id == telegram_id)
            .options(selectinload(User.company))
        )
        if not any_company:
            if company_id is None:
                stmt = stmt.where(User.company_id.is_(None))
            else:
                stmt = stmt.where(User.company_id == company_id)

        result = await self.session.execute(stmt.order_by(User.company_id.is_(None).desc()))
        return result.scalars().first()

    async def get_pending_agent_by_username(self, username: str, company_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User)
            .where(
                User.telegram_user_id == 0,
                func.lower(User.username) == username.lower(),
                User.role == UserRole.agent,
                User.company_id == company_id,
            )
            .options(selectinload(User.company))
            .order_by(User.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        role: UserRole = UserRole.client,
        company_id: Optional[int] = None,
    ) -> User:
        user = User(
            telegram_user_id=telegram_id,
            username=username,
            full_name=full_name,
            role=role,
            company_id=company_id,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_or_create(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        company_id: Optional[int] = None,
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id, company_id=company_id)
        if user:
            return user, False
        user = await self.create(telegram_id, username, full_name, company_id=company_id)
        return user, True

    async def update_last_active(self, telegram_id: int, company_id: Optional[int] = None) -> None:
        stmt = (
            update(User)
            .where(User.telegram_user_id == telegram_id)
            .values(last_active_at=func.now())
        )
        if company_id is None:
            stmt = stmt.where(User.company_id.is_(None))
        else:
            stmt = stmt.where(User.company_id == company_id)
        await self.session.execute(
            stmt
        )
        await self.session.commit()

    async def update_last_active_by_user_id(self, user_id: int) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_active_at=func.now())
        )
        await self.session.commit()

    async def update_phone(self, user_id: int, phone: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(phone=phone)
        )
        await self.session.commit()

    async def get_company_users_by_role(self, company_id: int, role: UserRole) -> list[User]:
        result = await self.session.execute(
            select(User).where(
                User.company_id == company_id,
                User.role == role,
                User.is_blocked == False,
            )
        )
        return list(result.scalars().all())

    async def get_company_users(self, company_id: int) -> list[User]:
        result = await self.session.execute(
            select(User).where(
                User.company_id == company_id,
                User.is_blocked == False,
            )
        )
        return list(result.scalars().all())
