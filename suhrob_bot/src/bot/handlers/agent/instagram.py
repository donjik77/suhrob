"""Instagram integration stub — billing gate only (no real API for MVP)."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from src.db.models import User, UserRole, Subscription, SubscriptionStatus, SubscriptionType
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director))


@router.message(F.text == "📷 Instagram ulash")
async def instagram_menu(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        active = (
            await session.execute(
                select(Subscription).where(
                    Subscription.company_id == db_user.company_id,
                    Subscription.subscription_type == SubscriptionType.instagram,
                    Subscription.status == SubscriptionStatus.active,
                ).order_by(Subscription.period_end.desc(), Subscription.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

    if active:
        text = (
            "📷 <b>Instagram integratsiyasi</b>\n\n"
            "✅ <b>Faol</b>\n\n"
            "Har bir yangi post avtomatik Instagram'ga ham yuboriladi.\n"
            "(Hozircha DM va Stories rejimi ishlab chiqilmoqda)"
        )
        await message.answer(text)
    else:
        text = (
            "📷 <b>Instagram integratsiyasi</b>\n\n"
            "Instagram'ni botga ulash — qo'shimcha xizmat.\n"
            "Narxi: <b>$19/oy</b>\n\n"
            "Foydalar:\n"
            "✅ Avtomatik post Instagram'ga\n"
            "✅ DM'da AI-yordamchi (tez orada)\n"
            "✅ Stories avtomatik (tez orada)\n\n"
            "Holati: Faol emas"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💳 Obuna bo'lish ($19/oy)", callback_data="instagram_subscribe"),
            InlineKeyboardButton(text="ℹ️ Batafsil", callback_data="instagram_info"),
        ]])
        await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "instagram_info")
async def instagram_info(callback: CallbackQuery):
    await callback.message.edit_text(
        "📷 <b>Instagram integratsiyasi — batafsil</b>\n\n"
        "Bot sizning Instagram biznes akkauntingizga ulanadi va:\n"
        "• Yangi obyekt qo'shganingizda avtomatik post qiladi\n"
        "• AI tavsif va hashtaglar yozadi\n"
        "• DM'larga avtomatik javob beradi (tez orada)\n\n"
        "Narx: <b>$19/oy</b> (asosiy obunaga qo'shimcha)\n\n"
        "Bugundan boshlab 7 kun bepul sinab ko'ring!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💳 Obuna bo'lish", callback_data="instagram_subscribe"),
        ]]),
    )
    await callback.answer()


@router.callback_query(F.data == "instagram_subscribe")
async def instagram_subscribe(callback: CallbackQuery, db_user: User):
    # Route to the director's balance/payment flow
    await callback.message.edit_text(
        "📷 Instagram obunasi uchun direktoring hisobini to'ldiring.\n\n"
        "Narx: <b>$19/oy</b>\n\n"
        "To'lov uchun direktorga xabar bering yoki o'zingiz direktor bo'lsangiz "
        "— /start → Profil → Balansni to'ldirish.",
    )
    await callback.answer()
