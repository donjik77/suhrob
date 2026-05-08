from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Property, PropertyStatus, PropertyType

NEIGHBORS: dict[str, list[str]] = {
    "Mirzo Ulug'bek": ["Yunusobod", "Mirobod"],
    "Yunusobod": ["Mirzo Ulug'bek", "Shayxontohur"],
    "Chilonzor": ["Yashnobod", "Sergeli"],
    "Yashnobod": ["Chilonzor", "Sergeli"],
    "Sergeli": ["Chilonzor", "Yashnobod"],
    "Yakkasaroy": ["Mirobod", "Shayxontohur"],
    "Mirobod": ["Mirzo Ulug'bek", "Yakkasaroy"],
    "Shayxontohur": ["Yunusobod", "Yakkasaroy"],
}


class SearchService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        company_id: int,
        district: Optional[str] = None,
        price_min: Optional[Decimal] = None,
        price_max: Optional[Decimal] = None,
        rooms: Optional[int] = None,
        property_type: Optional[PropertyType] = None,
        limit: int = 5,
    ) -> tuple[list[Property], bool]:
        """
        Returns (properties, is_exact_match).
        Tries exact match first; falls back to similar properties.
        """
        props = await self._query(company_id, district, price_min, price_max, rooms, property_type, limit)
        if props:
            return props, True

        similar = await self._search_similar(company_id, district, price_min, price_max, rooms, property_type, limit)
        return similar, False

    async def _query(
        self,
        company_id: int,
        district: Optional[str],
        price_min: Optional[Decimal],
        price_max: Optional[Decimal],
        rooms: Optional[int],
        property_type: Optional[PropertyType],
        limit: int,
    ) -> list[Property]:
        q = (
            select(Property)
            .where(Property.status == PropertyStatus.active)
            .where(Property.company_id == company_id)
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

    async def _search_similar(
        self,
        company_id: int,
        district: Optional[str],
        price_min: Optional[Decimal],
        price_max: Optional[Decimal],
        rooms: Optional[int],
        property_type: Optional[PropertyType],
        limit: int,
    ) -> list[Property]:
        # Expand price range ±20%
        exp_min = (price_min * Decimal("0.8")) if price_min is not None else None
        exp_max = (price_max * Decimal("1.2")) if price_max is not None else None

        # Add neighboring districts
        districts: list[Optional[str]] = [district] if district else [None]
        if district and district in NEIGHBORS:
            districts.extend(NEIGHBORS[district])

        # Allow ±1 room
        rooms_options: list[Optional[int]] = [rooms]
        if rooms is not None:
            if rooms > 1:
                rooms_options.append(rooms - 1)
            rooms_options.append(rooms + 1)

        q = (
            select(Property)
            .where(Property.status == PropertyStatus.active)
            .where(Property.company_id == company_id)
            .options(selectinload(Property.media), selectinload(Property.agent))
            .order_by(Property.created_at.desc())
            .limit(limit * 3)
        )

        if None not in districts:
            from sqlalchemy import or_
            q = q.where(or_(*[Property.location_district == d for d in districts if d]))

        if exp_min is not None:
            q = q.where(Property.price_usd >= exp_min)
        if exp_max is not None:
            q = q.where(Property.price_usd <= exp_max)

        if None not in rooms_options and rooms_options:
            from sqlalchemy import or_
            q = q.where(or_(*[Property.rooms == r for r in rooms_options if r is not None]))

        if property_type is not None:
            q = q.where(Property.property_type == property_type)

        result = await self.session.execute(q)
        candidates = list(result.scalars().all())

        # Score and sort by proximity
        scored = sorted(candidates, key=lambda p: self._score(p, district, price_min, price_max, rooms))
        return scored[:limit]

    def _score(
        self,
        prop: Property,
        district: Optional[str],
        price_min: Optional[Decimal],
        price_max: Optional[Decimal],
        rooms: Optional[int],
    ) -> float:
        score = 0.0

        if district and prop.location_district != district:
            score += 1.0

        if rooms is not None and prop.rooms != rooms:
            score += abs(prop.rooms - rooms) * 0.5

        mid_price = None
        if price_min is not None and price_max is not None:
            mid_price = (price_min + price_max) / 2
        elif price_max is not None:
            mid_price = price_max
        elif price_min is not None:
            mid_price = price_min

        if mid_price is not None and mid_price > 0:
            price_diff = abs(float(prop.price_usd) - float(mid_price)) / float(mid_price)
            score += price_diff

        return score
