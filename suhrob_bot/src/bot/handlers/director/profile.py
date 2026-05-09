"""Director profile with balance and subscription status."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.db.models import (
    Company, User, UserRole, UserBalance, Subscription, SubscriptionStatus, SubscriptionType
)
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter
from src.bot.handlers.director.company_scope import resolve_actor_company_id
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))


@router.message(F.text.in_([t("btn_my_profile"), "/profile"]))
async def director_profile(message: Message, db_user: User):
    company_id = await resolve_actor_company_id(db_user)
    async with AsyncSessionFactory() as session:
        balance_row = (
            await session.execute(
                select(UserBalance).where(UserBalance.user_id == db_user.id)
            )
        ).scalar_one_or_none()

        base_sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.company_id == company_id,
                    Subscription.subscription_type == SubscriptionType.base,
                    Subscription.status == SubscriptionStatus.active,
                ).order_by(Subscription.period_end.desc())
            )
        ).scalar_one_or_none()

        ig_sub = (
            await session.execute(
                select(Subscription).where(
                    Subscription.company_id == company_id,
                    Subscription.subscription_type == SubscriptionType.instagram,
                    Subscription.status == SubscriptionStatus.active,
                )
            )
        ).scalar_one_or_none()
        company = await session.get(Company, company_id) if company_id else None

    balance_usd = float(balance_row.balance_usd) if balance_row else 0.0
    balance_uzs = float(balance_row.balance_uzs) if balance_row else 0.0

    base_status = "✅ Faol" if base_sub else "❌ Faol emas"
    base_end = ""
    if base_sub and base_sub.period_end:
        base_end = f" (gacha {base_sub.period_end.strftime('%d.%m.%Y')})"

    ig_status = "✅ Faol" if ig_sub else "Faol emas"

    company_name = company.name if company else "—"

    text = (
        f"👤 <b>Mening profilim</b>\n\n"
        f"📋 Ism: <b>{db_user.full_name or '—'}</b>\n"
        f"🏢 Kompaniya: <b>{company_name}</b>\n"
        f"🆔 ID: <code>{db_user.telegram_user_id}</code>\n"
        f"📱 Telefon: {db_user.phone or '—'}\n\n"
        f"──────────────\n"
        f"💳 <b>Balans</b>\n"
        f"💵 USD: <b>${balance_usd:,.2f}</b>\n"
        f"💴 UZS: <b>{balance_uzs:,.0f} so'm</b>\n\n"
        f"──────────────\n"
        f"📋 <b>Obuna holati</b>\n"
        f"✅ Asosiy: {base_status}{base_end}\n"
        f"📷 Instagram: {ig_status}\n"
        f"💰 Narx: $49/oy (+ $19 Instagram)"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💳 Balansni to'ldirish", callback_data="topup_balance"),
            InlineKeyboardButton(text="📜 Tarix", callback_data="balance_history"),
        ],
        [InlineKeyboardButton(text="✏️ Profilni tahrirlash", callback_data="edit_profile")],
    ])
    await message.answer(text, reply_markup=kb)
