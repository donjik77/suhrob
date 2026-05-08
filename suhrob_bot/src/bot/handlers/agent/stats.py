from aiogram import Router, F
from aiogram.types import Message

from src.db.models import User, UserRole, PropertyStatus
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


@router.message(F.text == "🔵 📊 Statistika")
async def agent_stats(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select, func
        from datetime import datetime, timedelta
        from src.db.models import Property, SearchRequest

        now = datetime.utcnow()
        month_ago = now - timedelta(days=30)

        from src.db.models import LeadAssignment

        # Count active props
        active_count = await session.scalar(
            select(func.count()).where(
                Property.agent_id == db_user.id,
                Property.status == PropertyStatus.active,
            )
        )

        # Count sold props
        sold_count = await session.scalar(
            select(func.count()).where(
                Property.agent_id == db_user.id,
                Property.status == PropertyStatus.sold,
            )
        )

        # Sum views_count and contacts_count across agent's properties
        views_count = await session.scalar(
            select(func.coalesce(func.sum(Property.views_count), 0)).where(
                Property.agent_id == db_user.id,
            )
        )

        contacts_count = await session.scalar(
            select(func.coalesce(func.sum(Property.contacts_count), 0)).where(
                Property.agent_id == db_user.id,
            )
        )

        # Count leads assigned to this agent
        leads_count = await session.scalar(
            select(func.count()).where(
                LeadAssignment.agent_user_id == db_user.id,
            )
        )

        # Top search districts
        top_searches_result = await session.execute(
            select(
                SearchRequest.location_district,
                SearchRequest.rooms,
                func.count().label("cnt"),
            )
            .where(SearchRequest.created_at >= month_ago)
            .group_by(SearchRequest.location_district, SearchRequest.rooms)
            .order_by(func.count().desc())
            .limit(3)
        )
        top_searches = top_searches_result.all()

    lines = [
        t("stats_agent_title"),
        "",
        t("stats_active_props", count=active_count or 0),
        t("stats_sold_props", count=sold_count or 0),
        t("stats_views", count=int(views_count or 0)),
        t("stats_inquiries", count=int(leads_count or 0)),
        t("stats_contacts", count=int(contacts_count or 0)),
    ]

    if top_searches:
        lines.append("")
        lines.append(t("stats_top_searches"))
        for i, row in enumerate(top_searches, 1):
            district = row.location_district or "?"
            rooms_str = f"{row.rooms} xona" if row.rooms else "har xil"
            lines.append(f"{i}. {district}, {rooms_str}")

    await message.answer("\n".join(lines))
