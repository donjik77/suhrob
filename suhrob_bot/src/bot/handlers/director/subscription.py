from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import User, UserRole, SubscriptionStatus, PaymentMethod
from src.db.session import AsyncSessionFactory
from src.db.repositories.subscription_repo import SubscriptionRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.keyboards.payment import payment_method_kb, cancel_payment_kb
from src.bot.filters.role import RoleFilter
from src.bot.states.payment import PaymentStates
from src.utils.currency import usd_to_uzs
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.director, UserRole.developer))


@router.message(F.text == "💳 Obuna holati")
async def subscription_status(message: Message, db_user: User):
    if db_user.company_id is None:
        await message.answer("Kompaniya topilmadi.")
        return

    async with AsyncSessionFactory() as session:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_latest(db_user.company_id)

    if not sub:
        await message.answer("Obuna topilmadi.")
        return

    status_map = {
        SubscriptionStatus.active: t("sub_status_active"),
        SubscriptionStatus.pending_payment: t("sub_status_pending"),
        SubscriptionStatus.expired: t("sub_status_expired"),
        SubscriptionStatus.blocked: t("sub_status_blocked"),
    }
    status_label = status_map.get(sub.status, str(sub.status))

    start_str = sub.period_start.strftime("%d.%m.%Y") if sub.period_start else "—"
    end_str = sub.period_end.strftime("%d.%m.%Y") if sub.period_end else "—"

    text = t("sub_info", status=status_label, start=start_str, end=end_str, price=int(sub.price_usd))

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    if sub.status in (SubscriptionStatus.expired, SubscriptionStatus.blocked, SubscriptionStatus.pending_payment):
        builder.button(text=t("btn_pay"), callback_data="pay_start")

    await message.answer(text, reply_markup=builder.as_markup() if builder._markup_rows else None)


@router.callback_query(F.data == "pay_start")
async def start_payment(callback: CallbackQuery, state: FSMContext, db_user: User):
    await state.set_state(PaymentStates.choosing_method)
    await callback.message.answer(t("payment_method_select"), reply_markup=payment_method_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("pay_method:"), PaymentStates.choosing_method)
async def choose_payment_method(callback: CallbackQuery, state: FSMContext, db_user: User):
    method = callback.data.split(":")[1]
    await state.update_data(payment_method=method)

    async with AsyncSessionFactory() as session:
        settings_repo = SettingsRepository(session)
        price_usd = await settings_repo.get_float("monthly_price_usd", 49.0)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
        price_uzs = usd_to_uzs(price_usd, rate)

        if method == "crypto":
            address = await settings_repo.get("payment_crypto_address") or "—"
            network = await settings_repo.get("payment_crypto_network") or "USDT TRC-20"
            text = t("payment_instructions_crypto", network=network, address=address, price_usd=int(price_usd))
        else:
            card = await settings_repo.get(f"payment_{method}_card") or "—"
            holder = await settings_repo.get(f"payment_{method}_holder") or "—"
            text = t(
                "payment_instructions_card",
                method=method.upper(),
                card=card,
                holder=holder,
                price_usd=int(price_usd),
                price_uzs=price_uzs,
            )

    await state.set_state(PaymentStates.waiting_proof)
    await state.update_data(price_usd=price_usd, price_uzs=price_uzs)

    await callback.message.answer(text, reply_markup=cancel_payment_kb())
    await callback.answer()


@router.message(PaymentStates.waiting_proof, F.photo)
async def receive_payment_proof(message: Message, state: FSMContext, db_user: User):
    data = await state.get_data()
    method = data.get("payment_method", "")
    price_usd = data.get("price_usd", 49)
    file_id = message.photo[-1].file_id

    async with AsyncSessionFactory() as session:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_latest(db_user.company_id)

        if sub is None:
            sub = await sub_repo.create(db_user.company_id, price_usd=price_usd)

        sub.payment_proof_file_id = file_id
        sub.payment_method = PaymentMethod(method) if method else None
        sub.status = SubscriptionStatus.pending_payment
        await session.commit()
        sub_id = sub.id

        # Get company name
        from src.db.models import Company
        from sqlalchemy import select
        company = await session.get(Company, db_user.company_id)
        company_name = company.name if company else "—"

    await message.answer(t("payment_proof_received"))

    # Notify developer
    from src.config import settings as cfg
    from src.bot.keyboards.payment import payment_confirm_kb
    try:
        await message.bot.send_photo(
            chat_id=cfg.DEVELOPER_TELEGRAM_ID,
            photo=file_id,
            caption=t("dev_new_payment", company=company_name, price=int(price_usd), method=method.upper()),
            reply_markup=payment_confirm_kb(sub_id),
        )
    except Exception:
        pass

    await state.clear()


@router.callback_query(F.data == "pay_cancel")
async def cancel_payment(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ To'lov bekor qilindi.")
    await callback.answer()
