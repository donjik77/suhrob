from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Company, Property, PropertyStatus


async def get_active_property_for_client(
    property_id: int,
    company: Company | None,
    session: AsyncSession,
    *,
    with_agent: bool = False,
    with_media: bool = False,
) -> Property | None:
    if company is None:
        return None

    stmt = select(Property).where(
        Property.id == property_id,
        Property.status == PropertyStatus.active,
        Property.company_id == company.id,
    )
    if with_agent:
        stmt = stmt.options(selectinload(Property.agent))
    if with_media:
        stmt = stmt.options(selectinload(Property.media))

    result = await session.execute(stmt)
    return result.scalar_one_or_none()
