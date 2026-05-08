"""Client alert subscriptions — 'notify me when new property appears'."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from src.db.models import User, ClientAlert
from src.db.session import AsyncSessionFactory

router = Router()


@router.message(F.text == "🟡 🔔 Bildirishnomalar")
async def notifications_menu(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        alert = (
            await session.execute(
                select(ClientAlert).where(
                    ClientAlert.user_id == db_user.id,
                    ClientAlert.is_active == True,
                )
            )
        ).scalar_one_or_none()

    if alert:
        district = alert.location_district or "istalgan"
        price = f"${int(alert.price_max_usd)}" if alert.price_max_usd else "istalgan"
        rooms = str(alert.rooms) if alert.rooms else "istalgan"
        text = (
            "🔔 <b>Bildirishnomalar faol</b>\n\n"
            f"📍 Tuman: {district}\n"
            f"💰 Narx (max): {price}\n"
            f"🚪 Xonalar: {rooms}\n\n"
            "Yangi mos uy chiqsa, sizga xabar beramiz.\n\n"
            "❌ Bekor qilish uchun /unsubscribe yozing."
        )
    else:
        text = (
            "🔕 <b>Bildirishnomalar o'chirilgan</b>\n\n"
            "Uy qidirishdan so'ng 'Yangi chiqsa, xabar bering' tugmasini bosing.\n"
            "Siz ko'rsatgan parametrlarga mos yangi uy chiqsa, avtomatik xabar olasiz."
        )

    await message.answer(text)


@router.callback_query(F.data.startswith("subscribe_alert:"))
async def subscribe_to_alerts(callback: CallbackQuery, db_user: User):
    """
    Called after search returns no exact results.
    data format: subscribe_alert:{district}:{price_max}:{rooms}:{prop_type}
    """
    parts = callback.data.split(":")
    district = parts[1] if len(parts) > 1 else None
    price_max = float(parts[2]) if len(parts) > 2 and parts[2] != "None" else None
    rooms = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
    prop_type = parts[4] if len(parts) > 4 and parts[4] != "None" else None

    async with AsyncSessionFactory() as session:
        # Avoid duplicates
        existing = (
            await session.execute(
                select(ClientAlert).where(
                    ClientAlert.user_id == db_user.id,
                    ClientAlert.is_active == True,
                )
            )
        ).scalar_one_or_none()

        if existing:
            await callback.answer("Siz allaqachon obuna bo'lgansiz!", show_alert=True)
            return

        alert = ClientAlert(
            user_id=db_user.id,
            location_district=district,
            price_max_usd=price_max,
            rooms=rooms,
            property_type=prop_type,
            is_active=True,
        )
        session.add(alert)
        await session.commit()

    await callback.message.edit_text(
        "🔔 <b>Obuna faollashtirildi!</b>\n\n"
        f"Yangi obyekt chiqsa, sizga xabar beramiz.\n"
        f"📍 Tuman: {district or 'istalgan'}\n"
        f"💰 Narx: {'$' + str(int(price_max)) if price_max else 'istalgan'}\n\n"
        "❌ Obunani bekor qilish: /unsubscribe",
    )
    await callback.answer()


@router.message(F.text == "/unsubscribe")
async def unsubscribe(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import update
        await session.execute(
            update(ClientAlert)
            .where(ClientAlert.user_id == db_user.id)
            .values(is_active=False)
        )
        await session.commit()
    await message.answer("🔕 Barcha bildirishnomalar o'chirildi.")
