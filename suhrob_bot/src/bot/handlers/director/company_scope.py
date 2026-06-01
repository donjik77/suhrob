from sqlalchemy import func, select

from src.db.models import Company, User, UserRole
from src.db.session import AsyncSessionFactory


async def resolve_actor_company_id(db_user: User) -> int | None:
    if db_user.company_id:
        return db_user.company_id

    if db_user.role != UserRole.developer:
        return None

    async with AsyncSessionFactory() as session:
        active_count = await session.scalar(
            select(func.count(Company.id)).where(Company.is_active == True)
        )
        if active_count != 1:
            return None

        company = (
            await session.execute(
                select(Company)
                .where(Company.is_active == True)
                .order_by(Company.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return company.id if company else None
