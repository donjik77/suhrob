from aiogram import Router, F
from aiogram.types import Message

from src.db.models import User, UserRole, PropertyStatus
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


@router.message(F.text == "📊 Statistika")
async def agent_stats(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import case, select, func
        from datetime import datetime, timedelta, timezone
        from src.db.models import Property, SearchRequest

        now = datetime.now(timezone.utc)
        month_ago = now - timedelta(days=30)

        from src.db.models import LeadAssignment

        stats = await session.execute(
            select(
                func.count(Property.id).label("total"),
                func.coalesce(func.sum(case((Property.status == PropertyStatus.active, 1), else_=0)), 0).label("active"),
                func.coalesce(func.sum(case((Property.status == PropertyStatus.sold, 1), else_=0)), 0).label("sold"),
                func.coalesce(func.sum(Property.views_count), 0).label("views"),
                func.coalesce(func.sum(Property.contacts_count), 0).label("contacts"),
            )
            .where(Property.agent_id == db_user.id)
        )
        row = stats.one()

        active_count = row.active
        sold_count = row.sold
        views_count = row.views
        contacts_count = row.contacts

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
            .join(User, User.id == SearchRequest.user_id)
            .where(SearchRequest.created_at >= month_ago)
            .where(User.company_id == db_user.company_id)
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
