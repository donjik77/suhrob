from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User)
            .where(User.telegram_user_id == telegram_id)
            .options(selectinload(User.company))
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
    ) -> tuple[User, bool]:
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            return user, False
        user = await self.create(telegram_id, username, full_name)
        return user, True

    async def update_last_active(self, telegram_id: int) -> None:
        from sqlalchemy import func
        await self.session.execute(
            update(User)
            .where(User.telegram_user_id == telegram_id)
            .values(last_active_at=func.now())
        )
        await self.session.commit()

    async def update_phone(self, user_id: int, phone: str) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(phone=phone)
        )
        await self.session.commit()

    async def get_company_users(self, company_id: int) -> list[User]:
        result = await self.session.execute(
            select(User).where(User.company_id == company_id, User.is_blocked == False)
        )
        return list(result.scalars().all())
