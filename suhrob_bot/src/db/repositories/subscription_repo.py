from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Subscription, SubscriptionStatus


class SubscriptionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active(self, company_id: int) -> Optional[Subscription]:
        result = await self.session.execute(
            select(Subscription)
            .where(
                Subscription.company_id == company_id,
                Subscription.status == SubscriptionStatus.active,
            )
            .order_by(Subscription.period_end.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest(self, company_id: int) -> Optional[Subscription]:
        result = await self.session.execute(
            select(Subscription)
            .where(Subscription.company_id == company_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def is_blocked(self, company_id: int) -> bool:
        sub = await self.get_latest(company_id)
        if sub is None:
            return True
        return sub.status in (SubscriptionStatus.expired, SubscriptionStatus.blocked)

    async def create(self, company_id: int, price_usd=49, price_uzs=None) -> Subscription:
        sub = Subscription(
            company_id=company_id,
            price_usd=price_usd,
            price_uzs=price_uzs,
        )
        self.session.add(sub)
        await self.session.commit()
        await self.session.refresh(sub)
        return sub

    async def get_by_id(self, sub_id: int) -> Optional[Subscription]:
        result = await self.session.execute(
            select(Subscription).where(Subscription.id == sub_id)
        )
        return result.scalar_one_or_none()

    async def is_service_blocked(self) -> bool:
        """Returns True if there is no active subscription anywhere (whole service down)."""
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == SubscriptionStatus.active)
        )
        return (result.scalar_one() or 0) == 0
