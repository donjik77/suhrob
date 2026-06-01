"""Mortgage calculator handler."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.models import Company
from src.bot.handlers.client.property_access import get_active_property_for_client

router = Router()


async def _edit_or_answer(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    """Edit text if the message is a text-only message; answer new otherwise (e.g. photo messages)."""
    if callback.message.photo or callback.message.video or callback.message.document:
        await callback.message.answer(text, reply_markup=reply_markup)
    else:
        await callback.message.edit_text(text, reply_markup=reply_markup)

# Bank rates in %
BANKS = [
    ("Ipoteka Bank", 23),
    ("NBU", 24),
    ("Asaka Bank", 22),
]

DOWN_PAYMENT_OPTIONS = [10, 20, 30, 50]
TERM_OPTIONS = [5, 10, 15, 20, 25]


class MortgageState(StatesGroup):
    down_payment = State()
    term = State()


def _down_kb(property_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{p}%", callback_data=f"mort_dp:{property_id}:{p}") for p in DOWN_PAYMENT_OPTIONS],
        [InlineKeyboardButton(text="✏️ O'zim", callback_data=f"mort_dp:{property_id}:custom")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _term_kb(property_id: int, dp: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{t} yil", callback_data=f"mort_term:{property_id}:{dp}:{t}") for t in TERM_OPTIONS[:3]],
        [InlineKeyboardButton(text=f"{t} yil", callback_data=f"mort_term:{property_id}:{dp}:{t}") for t in TERM_OPTIONS[3:]],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("mortgage:"))
async def show_down_payment(callback: CallbackQuery, company: Company):
    property_id = int(callback.data.split(":")[1])
    from src.db.session import AsyncSessionFactory
    async with AsyncSessionFactory() as session:
        prop = await get_active_property_for_client(property_id, company, session)
    if not prop:
        await callback.answer("❌ Bunday obyekt mavjud emas yoki sotilgan", show_alert=True)
        return

    await _edit_or_answer(
        callback,
        "💰 <b>Ipoteka kalkulyatori</b>\n\nBoshlang'ich to'lov necha foiz?",
        reply_markup=_down_kb(property_id),
    )
    await callback.answer()


@router.message(MortgageState.down_payment)
async def custom_down_payment(message: Message, state: FSMContext):
    try:
        dp = int(message.text.strip().replace("%", ""))
        if not (1 <= dp <= 99):
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Iltimos, 1 dan 99 gacha bo'lgan raqam kiriting (masalan: 15):")
        return
    data = await state.get_data()
    property_id = data.get("property_id", 0)
    await state.clear()
    await message.answer(
        f"Boshlang'ich to'lov: <b>{dp}%</b>\nMuddat necha yil?",
        reply_markup=_term_kb(property_id, dp),
    )


@router.callback_query(F.data.startswith("mort_dp:"))
async def select_down_payment(callback: CallbackQuery, state: FSMContext):
    _, property_id_s, dp_s = callback.data.split(":")
    property_id = int(property_id_s)
    if dp_s == "custom":
        await state.set_state(MortgageState.down_payment)
        await state.update_data(property_id=property_id)
        await callback.message.edit_text("Boshlang'ich to'lov foizini kiriting (masalan: 15):")
        await callback.answer()
        return
    dp = int(dp_s)
    await callback.message.edit_text(
        f"Boshlang'ich to'lov: <b>{dp}%</b>\nMuddat necha yil?",
        reply_markup=_term_kb(property_id, dp),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mort_term:"))
async def show_calculation(callback: CallbackQuery, company: Company):
    parts = callback.data.split(":")
    property_id = int(parts[1])
    dp_pct = int(parts[2])
    years = int(parts[3])

    # Fetch property price
    from src.db.session import AsyncSessionFactory
    async with AsyncSessionFactory() as session:
        prop = await get_active_property_for_client(property_id, company, session)

    if not prop:
        await callback.answer("❌ Bunday obyekt mavjud emas yoki sotilgan", show_alert=True)
        return

    price = float(prop.price_usd)
    down_payment = price * dp_pct / 100
    loan = price - down_payment
    months = years * 12

    lines = [
        f"💰 <b>Ipoteka hisobi</b>\n",
        f"Narx: <b>${price:,.0f}</b>",
        f"Boshlang'ich to'lov ({dp_pct}%): <b>${down_payment:,.0f}</b>",
        f"Kredit: <b>${loan:,.0f}</b>",
        f"Muddat: <b>{years} yil</b>\n",
        "🏦 <b>Banklar bo'yicha:</b>\n",
    ]
    for bank_name, rate in BANKS:
        monthly_rate = rate / 100 / 12
        if monthly_rate > 0:
            monthly = loan * monthly_rate * (1 + monthly_rate) ** months / ((1 + monthly_rate) ** months - 1)
        else:
            monthly = loan / months
        total = monthly * months
        lines.append(f"🏦 <b>{bank_name}</b> ({rate}%)")
        lines.append(f"   Oylik: ~${monthly:,.0f}")
        lines.append(f"   Jami: ~${total:,.0f}\n")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📞 Agent bilan bog'lanish", callback_data=f"prop_contact:{property_id}")
    ]])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()
