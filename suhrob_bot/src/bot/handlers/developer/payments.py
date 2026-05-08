from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import User, UserRole, SubscriptionStatus
from src.db.session import AsyncSessionFactory
from src.db.repositories.subscription_repo import SubscriptionRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.db.repositories.user_repo import UserRepository
from src.bot.filters.role import RoleFilter
from src.bot.states.payment import PaymentStates
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.developer))


@router.callback_query(F.data.startswith("dev_pay_confirm:"))
async def confirm_payment(callback: CallbackQuery, db_user: User, bot: Bot):
    sub_id = int(callback.data.split(":")[1])

    async with AsyncSessionFactory() as session:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_id(sub_id)

        if not sub:
            await callback.answer("Obuna topilmadi", show_alert=True)
            return

        now = datetime.utcnow()
        sub.status = SubscriptionStatus.active
        sub.period_start = now
        sub.period_end = now + timedelta(days=30)
        sub.paid_at = now
        sub.confirmed_by = db_user.id
        await session.commit()

        start_str = sub.period_start.strftime("%d.%m.%Y")
        end_str = sub.period_end.strftime("%d.%m.%Y")

        # Notify all company users
        user_repo = UserRepository(session)
        users = await user_repo.get_company_users(sub.company_id)
        msg = t("payment_confirmed", start=start_str, end=end_str)
        for u in users:
            try:
                await bot.send_message(chat_id=u.telegram_user_id, text=msg)
            except Exception:
                pass

    await callback.message.edit_caption(
        callback.message.caption + "\n\n✅ Tasdiqlandi.",
        reply_markup=None,
    )
    await callback.answer("To'lov tasdiqlandi!", show_alert=True)


@router.callback_query(F.data.startswith("dev_pay_reject:"))
async def reject_payment_start(callback: CallbackQuery, state: FSMContext):
    sub_id = int(callback.data.split(":")[1])
    await state.set_state(PaymentStates.entering_reject_reason)
    await state.update_data(rejecting_sub_id=sub_id)
    await callback.message.answer(t("reject_reason_prompt"))
    await callback.answer()


@router.message(PaymentStates.entering_reject_reason)
async def enter_reject_reason(message: Message, state: FSMContext, db_user: User, bot: Bot):
    reason = message.text.strip()
    data = await state.get_data()
    sub_id = data.get("rejecting_sub_id")

    async with AsyncSessionFactory() as session:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_by_id(sub_id)

        if not sub:
            await message.answer("Obuna topilmadi.")
            await state.clear()
            return

        sub.status = SubscriptionStatus.expired
        sub.payment_proof_file_id = None
        await session.commit()

        # Notify director
        user_repo = UserRepository(session)
        users = await user_repo.get_company_users(sub.company_id)
        for u in users:
            if u.role in (UserRole.director,):
                try:
                    await bot.send_message(
                        chat_id=u.telegram_user_id,
                        text=t("payment_rejected", reason=reason),
                    )
                except Exception:
                    pass

    await message.answer("❌ To'lov rad etildi va direktoga xabar yuborildi.")
    await state.clear()


@router.message(F.text == "🟠 💰 Hisob chiqarish")
async def issue_invoice(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Company

        result = await session.execute(select(Company).where(Company.is_active == True))
        companies = list(result.scalars().all())

    if not companies:
        await message.answer("Kompaniyalar topilmadi.")
        return

    from src.bot.keyboards.payment import companies_list_kb
    await message.answer(t("invoice_select_company"), reply_markup=companies_list_kb(companies))


@router.callback_query(F.data.startswith("invoice_company:"))
async def invoice_select_company(callback: CallbackQuery, state: FSMContext):
    company_id = int(callback.data.split(":")[1])
    await state.update_data(invoice_company_id=company_id)

    async with AsyncSessionFactory() as session:
        settings_repo = SettingsRepository(session)
        default_price = int(await settings_repo.get_float("monthly_price_usd", 49.0))

    from src.bot.keyboards.payment import invoice_amount_kb
    await callback.message.answer(
        t("invoice_select_amount", default=default_price),
        reply_markup=invoice_amount_kb(default_price),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("invoice_amount:"))
async def invoice_select_amount(callback: CallbackQuery, state: FSMContext):
    amount_val = callback.data.split(":")[1]
    if amount_val == "custom":
        await state.set_state(PaymentStates.entering_custom_amount)
        await callback.message.answer(t("invoice_custom_prompt"))
        await callback.answer()
        return

    await _send_invoice(callback, state, int(amount_val))


@router.message(PaymentStates.entering_custom_amount)
async def enter_custom_invoice_amount(message: Message, state: FSMContext):
    from src.utils.parsers import parse_int
    amount = parse_int(message.text)
    if not amount or amount < 1:
        await message.answer("Noto'g'ri summa. Raqam kiriting.")
        return
    await _send_invoice(message, state, amount)


async def _send_invoice(event, state: FSMContext, amount_usd: int):
    data = await state.get_data()
    company_id = data.get("invoice_company_id")

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Company
        settings_repo = SettingsRepository(session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
        price_uzs = int(amount_usd * rate)

        company = await session.get(Company, company_id)
        company_name = company.name if company else "—"

        # Create pending subscription record
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.create(company_id, price_usd=amount_usd, price_uzs=price_uzs)
        sub.status = SubscriptionStatus.pending_payment
        await session.commit()

        # Notify all company users
        user_repo = UserRepository(session)
        users = await user_repo.get_company_users(company_id)

        from src.bot.keyboards.payment import payment_method_kb
        invoice_text = (
            f"💳 To'lov uchun hisob\n\n"
            f"Summa: ${amount_usd} (~{price_uzs:,} so'm)\n"
            f"To'lov uchun usulni tanlang:"
        )
        bot = event.bot if hasattr(event, "bot") else event.message.bot
        for u in users:
            try:
                await bot.send_message(
                    chat_id=u.telegram_user_id,
                    text=invoice_text,
                    reply_markup=payment_method_kb(),
                )
            except Exception:
                pass

    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.message.answer(t("invoice_sent", company=company_name))
        await event.answer()
    else:
        await event.answer(t("invoice_sent", company=company_name))


@router.message(F.text == "🟢 ✅ To'lovlarni tasdiqlash")
async def pending_payments(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Subscription, Company
        from sqlalchemy.orm import selectinload

        result = await session.execute(
            select(Subscription)
            .where(Subscription.status == SubscriptionStatus.pending_payment)
            .options(selectinload(Subscription.company))
        )
        subs = list(result.scalars().all())

    if not subs:
        await message.answer("Tasdiqlash uchun to'lovlar yo'q.")
        return

    from src.bot.keyboards.payment import payment_confirm_kb
    for sub in subs:
        cname = sub.company.name if sub.company else "—"
        method = sub.payment_method.value if sub.payment_method else "—"
        text = t("dev_new_payment", company=cname, price=int(sub.price_usd), method=method.upper())

        if sub.payment_proof_file_id:
            await message.answer_photo(
                photo=sub.payment_proof_file_id,
                caption=text,
                reply_markup=payment_confirm_kb(sub.id),
            )
        else:
            await message.answer(text, reply_markup=payment_confirm_kb(sub.id))
