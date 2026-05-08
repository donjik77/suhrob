"""Director balance top-up flow (manual proof-of-payment)."""
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, PhotoSize
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from src.db.models import (
    User, UserRole, UserBalance, BalanceTransaction, TransactionType,
    TransactionStatus, PaymentMethod
)
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter
from src.config import settings

router = Router()
router.message.filter(RoleFilter(UserRole.director, UserRole.developer))

AMOUNTS_USD = [25, 49, 98, 200]


class TopUpState(StatesGroup):
    waiting_amount = State()
    waiting_proof = State()


def _amount_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"${a}", callback_data=f"topup_amount:{a}") for a in AMOUNTS_USD],
        [InlineKeyboardButton(text="✏️ Boshqa summa", callback_data="topup_amount:custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _method_kb(amount: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 Click", callback_data=f"topup_method:{amount}:click")],
        [InlineKeyboardButton(text="💳 Humo", callback_data=f"topup_method:{amount}:humo")],
        [InlineKeyboardButton(text="💳 UzCard", callback_data=f"topup_method:{amount}:uzcard")],
        [InlineKeyboardButton(text="₿ Kripto", callback_data=f"topup_method:{amount}:crypto")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    amount = int(val)
    await callback.message.edit_text(
        f"💳 Summa: <b>${amount}</b>\n\nTo'lov usulini tanlang:",
        reply_markup=_method_kb(amount),
    )
    await callback.answer()


@router.message(TopUpState.waiting_amount)
async def custom_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip().replace("$", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("To'g'ri raqam kiriting (masalan: 75):")
        return
    await state.clear()
    await message.answer(
        f"💳 Summa: <b>${amount}</b>\n\nTo'lov usulini tanlang:",
        reply_markup=_method_kb(amount),
    )


@router.callback_query(F.data.startswith("topup_method:"))
async def select_method(callback: CallbackQuery, state: FSMContext, db_user: User):
    parts = callback.data.split(":")
    amount = int(parts[1])
    method = parts[2]

    async with AsyncSessionFactory() as session:
        from src.db.repositories.settings_repo import SettingsRepository
        sr = SettingsRepository(session)
        rate = float(await sr.get("currency_rate_uzs_per_usd", "12600"))

    amount_uzs = int(amount * rate)

    if method == "crypto":
        async with AsyncSessionFactory() as session:
            from src.db.repositories.settings_repo import SettingsRepository
            sr = SettingsRepository(session)
            address = await sr.get("payment_crypto_address", "Manzil sozlanmagan")
            network = await sr.get("payment_crypto_network", "USDT TRC-20")
        text = (
            f"₿ <b>Kripto orqali to'lov</b>\n\n"
            f"Tarmoq: <b>{network}</b>\n"
            f"Manzil:\n<code>{address}</code>\n\n"
            f"Summa: <b>${amount}</b>\n\n"
            f"To'lovni amalga oshiring va skrinshotni yuboring 👇\n\n"
            f"❌ Bekor qilish: /cancel"
        )
    else:
        async with AsyncSessionFactory() as session:
            from src.db.repositories.settings_repo import SettingsRepository
            sr = SettingsRepository(session)
            card = await sr.get(f"payment_{method}_card", "Karta sozlanmagan")
            holder = await sr.get(f"payment_{method}_holder", "")
        text = (
            f"💳 <b>{method.title()} orqali to'lov</b>\n\n"
            f"Karta raqami: <code>{card}</code>\n"
            f"Karta egasi: {holder}\n"
            f"Summa: <b>${amount}</b> (~{amount_uzs:,} so'm)\n\n"
            f"To'lovni amalga oshiring va chek rasmini yuboring 👇\n\n"
            f"❌ Bekor qilish: /cancel"
        )

    await state.set_state(TopUpState.waiting_proof)
    await state.update_data(amount=amount, method=method)
    await callback.message.edit_text(text)
    await callback.answer()


@router.message(TopUpState.waiting_proof, F.photo)
async def receive_proof(message: Message, state: FSMContext, db_user: User):
    fsm = await state.get_data()
    amount: int = fsm.get("amount", 0)
    method: str = fsm.get("method", "")
    await state.clear()

    photo: PhotoSize = message.photo[-1]  # highest resolution

    async with AsyncSessionFactory() as session:
        tx = BalanceTransaction(
            user_id=db_user.id,
            amount_usd=Decimal(str(amount)),
            transaction_type=TransactionType.topup,
            payment_method=PaymentMethod(method),
            description=f"Balans to'ldirish — {method}",
            status=TransactionStatus.pending,
            payment_proof_file_id=photo.file_id,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

    # Notify developer
    company_name = db_user.company.name if db_user.company else "—"
    dev_text = (
        f"💰 <b>Yangi balans to'ldirish</b>\n\n"
        f"🏢 Kompaniya: {company_name}\n"
        f"👤 Direktor: {db_user.full_name or db_user.username}\n"
        f"💵 Summa: ${amount}\n"
        f"💳 Usul: {method}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"confirm_tx:{tx.id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_tx:{tx.id}"),
    ]])
    try:
        await message.bot.send_photo(
            chat_id=settings.DEVELOPER_TELEGRAM_ID,
            photo=photo.file_id,
            caption=dev_text,
            reply_markup=kb,
        )
    except Exception:
        pass

    await message.answer(
        f"✅ Chek qabul qilindi!\n\n"
        f"To'lov tekshirilgandan so'ng balansiz yangilanadi.\n"
        f"Odatda 10-30 daqiqa ichida."
    )


@router.callback_query(F.data == "topup_cancel")
async def cancel_topup(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ To'ldirish bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data == "balance_history")
async def balance_history(callback: CallbackQuery, db_user: User):
    async with AsyncSessionFactory() as session:
        rows = (
            await session.execute(
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
