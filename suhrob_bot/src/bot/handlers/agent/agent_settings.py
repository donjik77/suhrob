from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.models import User, UserRole
from src.db.session import AsyncSessionFactory
from src.bot.filters.role import RoleFilter
from locales.uz import t

router = Router()
router.message.filter(RoleFilter(UserRole.agent, UserRole.director, UserRole.developer))


class AgentSettingsStates(StatesGroup):
    choosing = State()
    entering_name = State()
    entering_phone = State()


@router.message(F.text == "🔵 ⚙️ Sozlamalar")
async def settings_menu(message: Message, state: FSMContext, db_user: User):
    await state.clear()
    await state.set_state(AgentSettingsStates.choosing)

    name = db_user.full_name or "—"
    phone = db_user.phone or "—"

    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    kb = ReplyKeyboardBuilder()
    kb.button(text="✏️ Ismni o'zgartirish")
    kb.button(text="📞 Telefon raqamni o'zgartirish")
    kb.button(text="⬅️ Orqaga")
    kb.adjust(2, 1)

    await message.answer(
        t("agent_settings_menu", name=name, phone=phone),
        reply_markup=kb.as_markup(resize_keyboard=True),
    )


@router.message(AgentSettingsStates.choosing, F.text == "✏️ Ismni o'zgartirish")
async def prompt_name(message: Message, state: FSMContext):
    await state.set_state(AgentSettingsStates.entering_name)
    await message.answer(t("agent_settings_name_prompt"))


@router.message(AgentSettingsStates.entering_name, F.text)
async def save_name(message: Message, state: FSMContext, db_user: User):
    new_name = message.text.strip()
    if len(new_name) < 2:
        await message.answer("Ism kamida 2 ta belgidan iborat bo'lishi kerak.")
        return

    async with AsyncSessionFactory() as session:
        from sqlalchemy import update
        from src.db.models import User as UserModel
        await session.execute(
            update(UserModel)
            .where(UserModel.id == db_user.id)
            .values(full_name=new_name)
        )
        await session.commit()

    await state.clear()
    await message.answer(t("agent_settings_saved", field="Ism", value=new_name))


@router.message(AgentSettingsStates.choosing, F.text == "📞 Telefon raqamni o'zgartirish")
async def prompt_phone(message: Message, state: FSMContext):
    await state.set_state(AgentSettingsStates.entering_phone)
    await message.answer(t("agent_settings_phone_prompt"))


@router.message(AgentSettingsStates.entering_phone, F.text)
async def save_phone(message: Message, state: FSMContext, db_user: User):
    import re
    phone = re.sub(r"\s+", "", message.text.strip())
    if not re.match(r"^\+?\d{9,15}$", phone):
        await message.answer("Telefon raqamni to'g'ri formatda kiriting. Masalan: +998901234567")
        return

    async with AsyncSessionFactory() as session:
        from src.db.repositories.user_repo import UserRepository
        repo = UserRepository(session)
        await repo.update_phone(db_user.id, phone)

    await state.clear()
    await message.answer(t("agent_settings_saved", field="Telefon", value=phone))


@router.message(AgentSettingsStates.choosing, F.text == "⬅️ Orqaga")
async def go_back(message: Message, state: FSMContext, db_user: User):
    await state.clear()
    from src.bot.keyboards.agent import agent_menu_kb
    await message.answer(
        t("agent_menu_welcome", name=db_user.full_name or "Agent"),
        reply_markup=agent_menu_kb(db_user.role),
    )
