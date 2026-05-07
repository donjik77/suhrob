from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import User, UserRole, Property, ScheduledPost, ScheduledPostStatus, Company
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


@router.message(F.text == "📅 Rejalashtirilgan postlar")
async def show_scheduled_posts(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        q = (
            select(ScheduledPost)
            .where(ScheduledPost.status == ScheduledPostStatus.pending)
            .options(selectinload(ScheduledPost.property))
            .order_by(ScheduledPost.scheduled_at)
        )

        if db_user.role == UserRole.agent:
            q = q.join(Property, ScheduledPost.property_id == Property.id).where(
                Property.agent_id == db_user.id
            )
        else:
            company_id = db_user.company_id
            if not company_id:
                res = await session.execute(select(Company).limit(1))
                company = res.scalar_one_or_none()
                company_id = company.id if company else None
            if company_id:
                q = q.join(Property, ScheduledPost.property_id == Property.id).where(
                    Property.company_id == company_id
                )

        result = await session.execute(q)
        posts = list(result.scalars().all())

    if not posts:
        await message.answer("📅 Rejalashtirilgan postlar yo'q.")
        return

    builder = InlineKeyboardBuilder()
    lines = [f"📅 <b>Rejalashtirilgan postlar ({len(posts)} ta):</b>\n"]

    for post in posts:
        prop = post.property
        if not prop:
            continue
        dt = post.scheduled_at.strftime("%d.%m.%Y %H:%M")
        district = prop.location_district or "—"
        rooms = prop.rooms
        lines.append(f"• #{prop.id} — {district}, {rooms} xona → <b>{dt}</b>")
        builder.button(
            text=f"❌ #{prop.id} bekor qilish",
            callback_data=f"sched_cancel:{post.id}",
        )

    builder.adjust(1)
    await message.answer("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("sched_cancel:"))
async def cancel_scheduled_post(callback: CallbackQuery, db_user: User):
    post_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(ScheduledPost)
            .where(ScheduledPost.id == post_id)
            .options(selectinload(ScheduledPost.property))
        )
        post = result.scalar_one_or_none()

        if not post:
            await callback.answer("Post topilmadi", show_alert=True)
            return

        # Agents can only cancel their own posts
        if db_user.role == UserRole.agent:
            if post.property and post.property.agent_id != db_user.id:
                await callback.answer("Bu post sizga tegishli emas", show_alert=True)
                return

        await session.delete(post)
        await session.commit()

    await callback.answer("✅ Rejalashtirilgan post bekor qilindi", show_alert=True)
    await callback.message.delete()
