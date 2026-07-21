from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Company, Property, PropertyStatus, User


def resolve_client_company_id(
    company: Company | int | None,
    db_user: User | None = None,
) -> int | None:
    if isinstance(company, int):
        return company
    if company is not None:
        return company.id
    if db_user is not None and db_user.company_id:
        return db_user.company_id
    return None


async def get_active_property_for_client(
    property_id: int,
    company: Company | int | None,
    session: AsyncSession,
    *,
    with_agent: bool = False,
    with_media: bool = False,
) -> Property | None:
    company_id = resolve_client_company_id(company)
    if company_id is None:
        return None

    stmt = select(Property).where(
        Property.id == property_id,
        Property.status == PropertyStatus.active,
        Property.company_id == company_id,
    )
    if with_agent:
        stmt = stmt.options(selectinload(Property.agent))
    if with_media:
        stmt = stmt.options(selectinload(Property.media))

    result = await session.execute(stmt)
    return result.scalar_one_or_none()
