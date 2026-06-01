"""Director balance top-up flow (manual proof-of-payment)."""
from decimal import Decimal, InvalidOperation
import structlog

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    User, UserRole, BalanceTransaction, TransactionType,
    TransactionStatus, PaymentMethod
)
from src.bot.filters.role import RoleFilter
from src.config import settings
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.utils.payment_details import get_card_payment_details, get_crypto_payment_details
from src.bot.utils.payment_media import payment_photo_input

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.director, UserRole.developer))

AMOUNTS_USD = [25, 49, 98, 200]
TOPUP_METHODS = {PaymentMethod.click.value, PaymentMethod.humo.value, PaymentMethod.uzcard.value, PaymentMethod.crypto.value}
logger = structlog.get_logger(__name__)


class TopUpState(StatesGroup):
    waiting_amount = State()
    waiting_proof = State()


def _amount_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"${a}", callback_data=f"topup_amount:{a}") for a in AMOUNTS_USD],
        [InlineKeyboardButton(text="✏️ Boshqa summa", callback_data="topup_amount:custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _method_kb(amount: int | Decimal) -> InlineKeyboardMarkup:
    amount_cb = _format_amount_for_callback(Decimal(str(amount)))
    rows = [
        [InlineKeyboardButton(text="💳 Click", callback_data=f"topup_method:{amount_cb}:click")],
        [InlineKeyboardButton(text="💳 Humo", callback_data=f"topup_method:{amount_cb}:humo")],
        [InlineKeyboardButton(text="💳 UzCard", callback_data=f"topup_method:{amount_cb}:uzcard")],
        [InlineKeyboardButton(text="₿ Kripto", callback_data=f"topup_method:{amount_cb}:crypto")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _cancel_topup_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="topup_cancel")]
    ])


def _developer_topup_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"tx_confirm:{tx_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"tx_reject:{tx_id}"),
    ]])


def _parse_amount(raw: str) -> Decimal:
    try:
        amount = Decimal(raw.strip().replace("$", "").replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise ValueError("invalid amount") from None

    if amount <= 0 or amount > Decimal("100000"):
        raise ValueError("invalid amount")
    return amount.quantize(Decimal("0.01"))


def _format_amount(amount: Decimal) -> str:
    normalized = amount.normalize()
    return format(normalized, "f")


def _format_amount_for_callback(amount: Decimal) -> str:
    return _format_amount(amount).replace(":", "")


def _format_uzs(amount_uzs: Decimal) -> str:
    return f"{int(amount_uzs):,}".replace(",", " ")


def _topup_instruction(
    *,
    method: str,
    amount: Decimal,
    amount_uzs: Decimal,
    card: str | None = None,
    holder: str | None = None,
    address: str | None = None,
    network: str | None = None,
) -> str:
    if method == PaymentMethod.crypto.value:
        return (
            "₿ <b>Kripto orqali to'lov</b>\n\n"
            f"Tarmoq: <b>{network or 'USDT TRC-20'}</b>\n"
            f"Manzil:\n<code>{address or 'Manzil sozlanmagan'}</code>\n\n"
            f"Summa: <b>${_format_amount(amount)}</b>\n\n"
            "To'lovni amalga oshiring va tranzaksiya skrinshotini yuboring 👇"
        )

    return (
        f"💳 <b>{method.title()} orqali to'lov</b>\n\n"
        f"Karta raqami: <code>{card or 'Karta sozlanmagan'}</code>\n"
        f"Karta egasi: {holder or '—'}\n"
        f"Summa: <b>${_format_amount(amount)}</b> (~{_format_uzs(amount_uzs)} so'm)\n\n"
        "To'lovni amalga oshiring va chek rasmini yuboring 👇"
    )


async def _show_topup_instruction(
    callback: CallbackQuery,
    text: str,
    qr_file_id: str | None = None,
) -> None:
    if qr_file_id:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await callback.message.answer_photo(
                photo=payment_photo_input(qr_file_id),
                caption=text,
                reply_markup=_cancel_topup_kb(),
            )
            return
        except Exception:
            pass

    await callback.message.edit_text(text, reply_markup=_cancel_topup_kb())


async def _get_card_qr_file_id(sr: SettingsRepository, method: str) -> str | None:
    return (
        await sr.get(f"payment_{method}_qr_file_id")
        or await sr.get(f"payment_{method}_qr_photo")
        or await sr.get("payment_card_qr_file_id")
        or await sr.get("payment_card_qr_photo")
    )


@router.callback_query(F.data == "topup_balance")
async def start_topup(callback: CallbackQuery):
    await callback.message.edit_text(
        "💳 <b>Balansni to'ldirish</b>\n\nSummani tanlang:",
        reply_markup=_amount_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("topup_amount:"))
async def select_amount(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "custom":
        await state.set_state(TopUpState.waiting_amount)
        await callback.message.edit_text("Summani USD da kiriting (masalan: 75):")
        await callback.answer()
        return
    try:
        amount = _parse_amount(val)
    except ValueError:
        await callback.answer("❌ Summa noto'g'ri", show_alert=True)
        return
    await callback.message.edit_text(
        f"💳 Summa: <b>${_format_amount(amount)}</b>\n\nTo'lov usulini tanlang:",
        reply_markup=_method_kb(amount),
    )
    await callback.answer()


@router.message(TopUpState.waiting_amount)
async def custom_amount(message: Message, state: FSMContext):
    try:
        amount = _parse_amount(message.text)
    except ValueError:
        await message.answer("To'g'ri raqam kiriting (masalan: 75):")
        return
    await state.clear()
    await message.answer(
        f"💳 Summa: <b>${_format_amount(amount)}</b>\n\nTo'lov usulini tanlang:",
        reply_markup=_method_kb(amount),
    )


@router.callback_query(F.data.startswith("topup_method:"))
async def select_method(callback: CallbackQuery, state: FSMContext, db_user: User, db_session: AsyncSession):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("❌ Noto'g'ri so'rov", show_alert=True)
        return

    try:
        amount = _parse_amount(parts[1])
    except ValueError:
        await callback.answer("❌ Summa noto'g'ri", show_alert=True)
        return

    method = parts[2]
    if method not in TOPUP_METHODS:
        await callback.answer("❌ To'lov usuli noto'g'ri", show_alert=True)
        return

    sr = SettingsRepository(db_session)
    rate = await sr.get_decimal("currency_rate_uzs_per_usd", Decimal("12600"))
    amount_uzs = (amount * rate).quantize(Decimal("0.01"))
    qr_file_id = None

    if method == "crypto":
        address = await sr.get("payment_crypto_address", "Manzil sozlanmagan")
        network = await sr.get("payment_crypto_network", "USDT TRC-20")
        details = await get_crypto_payment_details(sr)
        address = details.address or address
        network = details.network or network
        text = _topup_instruction(
            method=method,
            amount=amount,
            amount_uzs=amount_uzs,
            address=address,
            network=network,
        )
    else:
        card = await sr.get(f"payment_{method}_card", "Karta sozlanmagan")
        holder = await sr.get(f"payment_{method}_holder", "")
        qr_file_id = await _get_card_qr_file_id(sr, method)
        details = await get_card_payment_details(sr, method)
        card = details.card or card
        holder = details.holder or holder
        qr_file_id = details.qr_file_id or qr_file_id
        text = _topup_instruction(
            method=method,
            amount=amount,
            amount_uzs=amount_uzs,
            card=card,
            holder=holder,
        )

    await state.set_state(TopUpState.waiting_proof)
    await state.update_data(amount=str(amount), amount_uzs=str(amount_uzs), method=method)
    await _show_topup_instruction(callback, text, qr_file_id)
    await callback.answer()


@router.message(TopUpState.waiting_proof, F.photo)
async def receive_proof(message: Message, state: FSMContext, db_user: User, db_session: AsyncSession):
    fsm = await state.get_data()
    amount_raw = fsm.get("amount", "0")
    amount_uzs_raw = fsm.get("amount_uzs", "0")
    method: str = fsm.get("method", "")
    try:
        amount = Decimal(str(amount_raw))
        amount_uzs = Decimal(str(amount_uzs_raw))
        payment_method = PaymentMethod(method)
    except (InvalidOperation, ValueError):
        await state.clear()
        await message.answer("❌ To'lov ma'lumotlari eskirgan. Iltimos, qaytadan boshlang.")
        return

    photo: PhotoSize = message.photo[-1]  # highest resolution

    tx = BalanceTransaction(
        user_id=db_user.id,
        amount_usd=amount,
        amount_uzs=amount_uzs,
        transaction_type=TransactionType.topup,
        payment_method=payment_method,
        description=f"Balans to'ldirish — {method}",
        status=TransactionStatus.pending,
        payment_proof_file_id=photo.file_id,
    )
    db_session.add(tx)
    await db_session.commit()
    await db_session.refresh(tx)

    # Notify developer
    from src.db.models import Company
    company = await db_session.get(Company, db_user.company_id) if db_user.company_id else None
    company_name = company.name if company else "—"
    dev_text = (
        f"💰 <b>Yangi balans to'ldirish</b>\n\n"
        f"🏢 Kompaniya: {company_name}\n"
        f"👤 Direktor: {db_user.full_name or db_user.username}\n"
        f"💵 Summa: ${_format_amount(amount)} (~{_format_uzs(amount_uzs)} so'm)\n"
        f"💳 Usul: {method}\n"
        f"🆔 Tranzaksiya ID: <code>{tx.id}</code>"
    )
    notified = True
    try:
        await message.bot.send_photo(
            chat_id=settings.DEVELOPER_TELEGRAM_ID,
            photo=photo.file_id,
            caption=dev_text,
            reply_markup=_developer_topup_kb(tx.id),
        )
    except Exception as exc:
        notified = False
        logger.exception("topup_developer_notify_failed", tx_id=tx.id, error=str(exc))

    await message.answer(
        "✅ <b>Chek qabul qilindi</b>\n\n"
        "Sizning to'lovingiz tekshiruvga yuborildi. "
        "Tasdiqlangandan so'ng balans yangilanadi."
        + ("" if notified else "\n\n⚠️ Developer xabarnomasini yuborib bo'lmadi. Administrator bilan bog'laning.")
    )
    await state.clear()


@router.message(TopUpState.waiting_proof, ~F.photo)
async def receive_invalid_payment_proof(message: Message):
    await message.answer(
        "❌ Iltimos, to'lov cheki yoki tranzaksiya skrinshotini rasm sifatida yuboring.",
        reply_markup=_cancel_topup_kb(),
    )


@router.callback_query(F.data == "topup_cancel")
async def cancel_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ To'ldirish bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data == "balance_history")
async def balance_history(callback: CallbackQuery, db_user: User, db_session: AsyncSession):
    rows = (
        await db_session.execute(
            select(BalanceTransaction)
            .where(BalanceTransaction.user_id == db_user.id)
            .order_by(BalanceTransaction.created_at.desc())
            .limit(10)
        )
    ).scalars().all()

    if not rows:
        await callback.answer("Tranzaksiyalar yo'q.", show_alert=True)
        return

    lines = ["📜 <b>Oxirgi 10 tranzaksiya</b>\n"]
    for tx in rows:
        icon = "➕" if tx.transaction_type == TransactionType.topup else "➖"
        status_icon = "✅" if tx.status == TransactionStatus.completed else ("⏳" if tx.status == TransactionStatus.pending else "❌")
        amount = f"${tx.amount_usd}" if tx.amount_usd else ""
        lines.append(
            f"{icon} {amount} — {tx.transaction_type.value} {status_icon} "
            f"({tx.created_at.strftime('%d.%m.%Y')})"
        )

    await callback.message.edit_text("\n".join(lines))
    await callback.answer()
