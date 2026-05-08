from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.models import User, UserRole, Company
from src.db.session import AsyncSessionFactory
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.filters.role import RoleFilter

router = Router()
router.message.filter(RoleFilter(UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.developer))


class SettingEditStates(StatesGroup):
    entering_key = State()
    entering_value = State()


@router.message(F.text == "🔵 ⚙️ Tizim sozlamalari")
async def system_settings(message: Message, db_user: User):
    async with AsyncSessionFactory() as session:
        repo = SettingsRepository(session)
        all_settings = await repo.get_all()

    lines = ["⚙️ Tizim sozlamalari:\n"]
    for key, value in sorted(all_settings.items()):
        display_val = value if len(value) < 40 else value[:37] + "..."
        lines.append(f"• {key} = {display_val}")

    lines.append("\n/set_key <kalit> <qiymat> — qiymatni o'zgartirish")
    await message.answer("\n".join(lines))


@router.message(F.text.startswith("/set_key "))
async def set_setting(message: Message, db_user: User):
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer("Foydalanish: /set_key <kalit> <qiymat>")
        return

    key = parts[1].strip()
    value = parts[2].strip()

    async with AsyncSessionFactory() as session:
        repo = SettingsRepository(session)
        await repo.set(key, value, updated_by=db_user.id)

    await message.answer(f"✅ {key} = {value} qilib saqlandi.")


# ─── New company FSM ──────────────────────────────────────────────────────────

class NewCompanyStates(StatesGroup):
    entering_name = State()
    entering_channel = State()


@router.message(Command("new_company"))
async def cmd_new_company(message: Message, state: FSMContext):
    await state.set_state(NewCompanyStates.entering_name)
    await message.answer("🏢 Yangi kompaniya nomini kiriting:")


@router.message(NewCompanyStates.entering_name)
async def enter_company_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Ism bo'sh bo'lmasin.")
        return
    await state.update_data(company_name=name)
    await state.set_state(NewCompanyStates.entering_channel)
    await message.answer(
        "Telegram kanal ID kiriting:\nMisol: @my_channel yoki -1001234567890\n\n/skip — keyinroq qo'shish"
    )


@router.message(NewCompanyStates.entering_channel)
async def enter_company_channel(message: Message, state: FSMContext):
    data = await state.get_data()
    raw = message.text.strip()
    channel = None if raw == "/skip" else raw

    async with AsyncSessionFactory() as session:
        company = Company(name=data["company_name"], telegram_channel_id=channel, is_active=True)
        session.add(company)
        await session.commit()
        await session.refresh(company)
        company_id = company.id
        company_name = company.name

    await state.clear()
    await message.answer(
        f"✅ Kompaniya yaratildi!\n\n"
        f"Nomi: {company_name}\n"
        f"ID: {company_id}\n"
        f"Kanal: {channel or '—'}\n\n"
        f"Direktor tayinlash:\n"
        f"/set_role <tg_id> director {company_id}\n\n"
        f"Agent qo'shish:\n"
        f"/set_role <tg_id> agent {company_id}"
    )


# ─── Set user role ─────────────────────────────────────────────────────────────

@router.message(Command("set_role"))
async def cmd_set_role(message: Message):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer(
            "Foydalanish:\n/set_role <tg_id> <rol> [company_id]\n\n"
            "Rollar: agent, director, client, developer\n\n"
            "Misol:\n/set_role 123456789 agent 1"
        )
        return

    try:
        tg_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Noto'g'ri Telegram ID.")
        return

    role_str = parts[2].lower()
    if role_str not in ("agent", "director", "client", "developer"):
        await message.answer("❌ Noto'g'ri rol. Rollar: agent, director, client, developer")
        return

    company_id = None
    if len(parts) >= 4:
        try:
            company_id = int(parts[3])
        except ValueError:
            await message.answer("❌ Noto'g'ri company_id.")
            return

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_user_id == tg_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_user_id=tg_id,
                role=UserRole(role_str),
                company_id=company_id,
            )
            session.add(user)
            action = "yaratildi"
        else:
            user.role = UserRole(role_str)
            if company_id is not None:
                user.company_id = company_id
            action = "yangilandi"

        await session.commit()

    msg = f"✅ Foydalanuvchi {action}\nTG ID: {tg_id}\nRol: {role_str}"
    if company_id:
        msg += f"\nKompaniya ID: {company_id}"
    await message.answer(msg)
