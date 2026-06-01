from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery

from src.db.models import UserRole, User


class RoleFilter(Filter):
    def __init__(self, *roles: UserRole):
        self.roles = set(roles)

    async def __call__(self, event: Message | CallbackQuery, db_user: User | None = None) -> bool:
        if db_user is None:
            return False
        return db_user.role in self.roles
