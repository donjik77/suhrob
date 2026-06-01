from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User, UserRole


class StatsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_new_users_stats(self, company_id: int, days: int = 30) -> dict:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=days)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total = await self.session.scalar(
            select(func.count(User.id)).where(
                User.company_id == company_id,
                User.role == UserRole.client,
            )
        )
        new_period = await self.session.scalar(
            select(func.count(User.id)).where(
                User.company_id == company_id,
                User.role == UserRole.client,
                User.created_at >= period_start,
            )
        )
        new_today = await self.session.scalar(
            select(func.count(User.id)).where(
                User.company_id == company_id,
                User.role == UserRole.client,
                User.created_at >= today_start,
            )
        )

        return {
            "total": total or 0,
            "new_period": new_period or 0,
            "new_today": new_today or 0,
            "days": days,
        }
