from decimal import Decimal
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Property, PropertyStatus, PropertyType


class PropertyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, property_id: int) -> Optional[Property]:
        result = await self.session.execute(
            select(Property)
            .where(Property.id == property_id)
            .options(
                selectinload(Property.media),
                selectinload(Property.agent),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> Property:
        prop = Property(**kwargs)
        self.session.add(prop)
        await self.session.commit()
        await self.session.refresh(prop)
        return prop

    async def search(
        self,
        company_id: int,
        district: Optional[str] = None,
        price_min: Optional[Decimal] = None,
        price_max: Optional[Decimal] = None,
        rooms: Optional[int] = None,
        property_type: Optional[PropertyType] = None,
        limit: int = 5,
    ) -> list[Property]:
        q = (
            select(Property)
            .where(Property.company_id == company_id, Property.status == PropertyStatus.active)
            .options(selectinload(Property.media), selectinload(Property.agent))
            .order_by(Property.created_at.desc())
            .limit(limit)
        )
        if district:
            q = q.where(Property.location_district == district)
        if price_min is not None:
            q = q.where(Property.price_usd >= price_min)
        if price_max is not None:
            q = q.where(Property.price_usd <= price_max)
        if rooms is not None:
            q = q.where(Property.rooms == rooms)
        if property_type is not None:
            q = q.where(Property.property_type == property_type)

        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_active_districts(self, company_id: int) -> list[str]:
        result = await self.session.execute(
            select(Property.location_district)
            .where(Property.company_id == company_id, Property.status == PropertyStatus.active)
            .distinct()
            .order_by(Property.location_district)
        )
        return [row[0] for row in result.all()]

    async def get_agent_properties(
        self, agent_id: int, offset: int = 0, limit: int = 5
    ) -> tuple[list[Property], int]:
        count_result = await self.session.execute(
            select(func.count()).where(Property.agent_id == agent_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Property)
            .where(Property.agent_id == agent_id)
            .options(selectinload(Property.media))
            .order_by(Property.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def update_status(self, property_id: int, status: PropertyStatus) -> None:
        from sqlalchemy import update
        await self.session.execute(
            update(Property).where(Property.id == property_id).values(status=status)
        )
        await self.session.commit()

    async def update_telegram_post_id(self, property_id: int, post_id: str) -> None:
        from sqlalchemy import update
        await self.session.execute(
            update(Property).where(Property.id == property_id).values(telegram_post_id=post_id)
        )
        await self.session.commit()

    async def get_company_properties(
        self, company_id: int, offset: int = 0, limit: int = 5
    ) -> tuple[list[Property], int]:
        count_result = await self.session.execute(
            select(func.count()).where(Property.company_id == company_id)
        )
        total = count_result.scalar_one()

        result = await self.session.execute(
            select(Property)
            .where(Property.company_id == company_id)
            .options(selectinload(Property.media), selectinload(Property.agent))
            .order_by(Property.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total
