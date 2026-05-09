from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from src.db.models import User, UserRole, SubscriptionStatus, PaymentMethod, PaymentSource
from src.db.session import AsyncSessionFactory
from src.db.repositories.subscription_repo import SubscriptionRepository
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.keyboards.payment import payment_method_kb, cancel_payment_kb
from src.bot.filters.role import RoleFilter
from src.bot.handlers.director.company_scope import resolve_actor_company_id
from src.bot.states.payment import PaymentStates
from src.bot.utils.payment_details import get_card_payment_details, get_crypto_payment_details
from src.bot.utils.payment_media import payment_photo_input
from src.utils.currency import usd_to_uzs
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


CARD_PAYMENT_METHODS = {
    PaymentMethod.click.value,
    PaymentMethod.humo.value,
    PaymentMethod.uzcard.value,
}


async def _send_payment_instruction(callback: CallbackQuery, text: str, qr_file_id: str | None = None) -> None:
    if qr_file_id:
        try:
            await callback.message.answer_photo(
                photo=payment_photo_input(qr_file_id),
                caption=text,
                reply_markup=cancel_payment_kb(),
            )
            return
        except Exception:
            pass

    await callback.message.answer(text, reply_markup=cancel_payment_kb())


async def _get_card_qr_file_id(settings_repo: SettingsRepository, method: str) -> str | None:
    return (
        await settings_repo.get(f"payment_{method}_qr_file_id")
        or await settings_repo.get(f"payment_{method}_qr_photo")
        or await settings_repo.get("payment_card_qr_file_id")
        or await settings_repo.get("payment_card_qr_photo")
    )


@router.message(F.text == t("btn_subscription"))
async def subscription_status(message: Message, db_user: User):
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await message.answer("Kompaniya topilmadi.")
        return

    async with AsyncSessionFactory() as session:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_latest(company_id)
        is_due = await sub_repo.is_blocked(company_id)
        settings_repo = SettingsRepository(session)
        default_price = await settings_repo.get_float("monthly_price_usd", 49.0)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()

    if not sub:
        builder.button(text=t("btn_pay"), callback_data="pay_start")
        await message.answer(
            t("sub_info", status=t("sub_status_pending"), start="—", end="—", price=int(default_price)),
            reply_markup=builder.as_markup(),
        )
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

    if is_due:
        builder.button(text=t("btn_pay"), callback_data="pay_start")

    await message.answer(text, reply_markup=builder.as_markup() if builder._markup_rows else None)


@router.callback_query(F.data == "pay_start")
async def start_payment(callback: CallbackQuery, state: FSMContext, db_user: User):
    await state.set_state(PaymentStates.choosing_method)
    await callback.message.answer(t("payment_method_select"), reply_markup=payment_method_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("pay_method:"))
async def choose_payment_method(callback: CallbackQuery, state: FSMContext, db_user: User):
    method = callback.data.split(":")[1]
    if method not in CARD_PAYMENT_METHODS and method != PaymentMethod.crypto.value:
        await callback.answer("To'lov usuli noto'g'ri", show_alert=True)
        return

    await state.update_data(payment_method=method)
    qr_file_id = None

    async with AsyncSessionFactory() as session:
        settings_repo = SettingsRepository(session)
        company_id = await resolve_actor_company_id(db_user)
        sub = None
        if company_id is not None:
            sub_repo = SubscriptionRepository(session)
            sub = await sub_repo.get_latest(company_id)

        price_usd = (
            float(sub.price_usd)
            if sub and sub.price_usd
            else await settings_repo.get_float("monthly_price_usd", 49.0)
        )
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)
        price_uzs = usd_to_uzs(price_usd, rate)

        if method == "crypto":
            address = await settings_repo.get("payment_crypto_address") or "Manzil sozlanmagan"
            network = await settings_repo.get("payment_crypto_network") or "USDT TRC-20"
            details = await get_crypto_payment_details(settings_repo)
            address = details.address or address
            network = details.network or network
            text = t("payment_instructions_crypto", network=network, address=address, price_usd=int(price_usd))
        else:
            card = await settings_repo.get(f"payment_{method}_card") or "Karta sozlanmagan"
            holder = await settings_repo.get(f"payment_{method}_holder") or "—"
            qr_file_id = await _get_card_qr_file_id(settings_repo, method)
            details = await get_card_payment_details(settings_repo, method)
            card = details.card or card
            holder = details.holder or holder
            qr_file_id = details.qr_file_id or qr_file_id
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

    await _send_payment_instruction(callback, text, qr_file_id)
    await callback.answer()


@router.message(PaymentStates.waiting_proof, F.photo)
async def receive_payment_proof(message: Message, state: FSMContext, db_user: User):
    data = await state.get_data()
    method = data.get("payment_method", "")
    price_usd = data.get("price_usd", 49)
    file_id = message.photo[-1].file_id
    company_id = await resolve_actor_company_id(db_user)
    if company_id is None:
        await message.answer("Kompaniya topilmadi.")
        await state.clear()
        return

    async with AsyncSessionFactory() as session:
        sub_repo = SubscriptionRepository(session)
        sub = await sub_repo.get_latest(company_id)

        if sub is None:
            sub = await sub_repo.create(company_id, price_usd=price_usd)

        sub.payment_proof_file_id = file_id
        sub.payment_method = PaymentMethod(method) if method else None
        sub.payment_source = PaymentSource.manual_proof
        sub.status = SubscriptionStatus.pending_payment
        await session.commit()
        sub_id = sub.id

        # Get company name
        from src.db.models import Company
        from sqlalchemy import select
        company = await session.get(Company, company_id)
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
