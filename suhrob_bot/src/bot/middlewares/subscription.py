from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject, Message, CallbackQuery

from src.db.models import UserRole, User
from src.bot.keyboards.payment import payment_method_kb
from src.bot.states.payment import PaymentStates
from src.db.repositories.subscription_repo import SubscriptionRepository
from locales.uz import t


class SubscriptionMiddleware(BaseMiddleware):
    """
    Blocks agent/director actions when the company subscription is due.
    Payment flow callbacks and proof uploads must still pass through.
    Must run after AuthMiddleware.
    """

    async def _is_payment_flow_event(self, event: TelegramObject, data: dict[str, Any]) -> bool:
        if isinstance(event, CallbackQuery):
            callback_data = event.data or ""
            return (
                callback_data == "pay_start"
                or callback_data == "pay_cancel"
                or callback_data.startswith("pay_method:")
                or callback_data.startswith("pay_invoice_method:")
            )

        if isinstance(event, Message):
            text = event.text or ""
            if text.startswith("/start"):
                return True

            state: FSMContext | None = data.get("state")
            if state is not None:
                return await state.get_state() == PaymentStates.waiting_proof.state

        return False

    async def _send_payment_required(self, event: Message | CallbackQuery) -> None:
        text = t("subscription_payment_required")
        if isinstance(event, Message):
            await event.answer(text, reply_markup=payment_method_kb())
            return

        if event.message:
            await event.message.answer(text, reply_markup=payment_method_kb())
        await event.answer()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("db_user")

        if user is None:
            return await handler(event, data)

        # Developer and clients are not part of the company staff subscription gate.
        if user.role in (UserRole.developer, UserRole.client):
            return await handler(event, data)

        if user.role not in (UserRole.agent, UserRole.director):
            return await handler(event, data)

        if await self._is_payment_flow_event(event, data):
            return await handler(event, data)

        session = data.get("db_session")
        if session is None:
            return await handler(event, data)

        repo = SubscriptionRepository(session)

        if user.company_id:
            blocked = await repo.is_blocked(user.company_id)
        else:
            blocked = False

        if blocked:
            if isinstance(event, (Message, CallbackQuery)):
                await self._send_payment_required(event)
            return

        return await handler(event, data)
