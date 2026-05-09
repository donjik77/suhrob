"""Shared profile handler for agent and director roles."""
import re
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.db.models import User, UserRole
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director))
router.callback_query.filter(RoleFilter(UserRole.agent, UserRole.director))


class EditProfileStates(StatesGroup):
    editing_name = State()
    editing_phone = State()


@router.message(F.text.in_(["⚙️ Mening profilim", "/profile"]))
async def show_profile(message: Message, db_user: User):
    company_name = db_user.company.name if db_user.company else "—"
    profile_text = (
        f"👤 <b>Mening profilim</b>\n\n"
        f"📛 <b>Ism:</b> {db_user.full_name or '—'}\n"
        f"📞 <b>Telefon:</b> {db_user.phone or '—'}\n"
        f"🆔 <b>Telegram ID:</b> <code>{db_user.telegram_user_id}</code>\n"
        f"👥 <b>Username:</b> @{db_user.username or '—'}\n"
        f"🏢 <b>Kompaniya:</b> {company_name}\n"
        f"🎭 <b>Rol:</b> {db_user.role.value}\n"
        f"📅 <b>Ro'yxatdan o'tgan:</b> {db_user.created_at.strftime('%d.%m.%Y')}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="profile_edit_name")],
        [InlineKeyboardButton(text="✏️ Telefonni o'zgartirish", callback_data="profile_edit_phone")],
    ])
    await message.answer(profile_text, parse_mode='HTML', reply_markup=kb)


@router.callback_query(F.data == "profile_edit_name")
async def edit_name_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Yangi ismni kiriting (3-100 ta belgi):")
    await state.set_state(EditProfileStates.editing_name)
    await callback.answer()


@router.callback_query(F.data == "edit_profile")
async def edit_profile_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ismni o'zgartirish", callback_data="profile_edit_name")],
        [InlineKeyboardButton(text="✏️ Telefonni o'zgartirish", callback_data="profile_edit_phone")],
    ])
    await callback.message.answer("✏️ Qaysi ma'lumotni o'zgartirmoqchisiz?", reply_markup=kb)
    await callback.answer()


@router.message(StateFilter(EditProfileStates.editing_name))
async def edit_name_save(message: Message, state: FSMContext, db_user: User):
    new_name = message.text.strip()
    if len(new_name) < 3 or len(new_name) > 100:
        await message.answer("❌ Ism noto'g'ri. Qaytadan kiriting:")
        return
    async with AsyncSessionFactory() as session:
        from sqlalchemy import update
        from src.db.models import User as UserModel
        await session.execute(
            update(UserModel).where(UserModel.id == db_user.id).values(full_name=new_name)
        )
        await session.commit()
    await message.answer(f"✅ Ism o'zgartirildi: <b>{new_name}</b>", parse_mode='HTML')
    await state.clear()


@router.callback_query(F.data == "profile_edit_phone")
async def edit_phone_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✏️ Yangi telefon raqamini kiriting (+998XXXXXXXXX):")
    await state.set_state(EditProfileStates.editing_phone)
    await callback.answer()


@router.message(StateFilter(EditProfileStates.editing_phone))
async def edit_phone_save(message: Message, state: FSMContext, db_user: User):
    new_phone = message.text.strip()
    if not re.match(r'^\+998\d{9}$', new_phone):
        await message.answer("❌ Format noto'g'ri (+998901234567). Qaytadan:")
        return
    async with AsyncSessionFactory() as session:
        from sqlalchemy import update
        from src.db.models import User as UserModel
        await session.execute(
            update(UserModel).where(UserModel.id == db_user.id).values(phone=new_phone)
        )
        await session.commit()
    await message.answer(f"✅ Telefon o'zgartirildi: <b>{new_phone}</b>", parse_mode='HTML')
    await state.clear()
