from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.db.models import User, UserRole
from src.db.session import AsyncSessionFactory
from src.db.repositories.settings_repo import SettingsRepository
from src.bot.filters.role import RoleFilter

router = Router()
router.message.filter(RoleFilter(UserRole.developer))
router.callback_query.filter(RoleFilter(UserRole.developer))


class SettingEditStates(StatesGroup):
    entering_key = State()
    entering_value = State()


@router.message(F.text == "⚙️ Tizim sozlamalari")
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


@router.message(F.text == "🏢 Kompaniyalar")
async def list_companies(message: Message):
    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        from src.db.models import Company, Subscription, SubscriptionStatus

        result = await session.execute(select(Company))
        companies = list(result.scalars().all())

    if not companies:
        await message.answer("Kompaniyalar yo'q.")
        return

    lines = ["🏢 Barcha kompaniyalar:\n"]
    for c in companies:
        status = "✅ Faol" if c.is_active else "❌ Nofaol"
        lines.append(f"• {c.name} [{status}] (ID: {c.id})")

    await message.answer("\n".join(lines))
