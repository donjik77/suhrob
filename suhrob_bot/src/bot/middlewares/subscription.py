from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject, Message, CallbackQuery, Update

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

    def _message_or_callback(self, event: TelegramObject) -> Message | CallbackQuery | None:
        if isinstance(event, (Message, CallbackQuery)):
            return event
        if isinstance(event, Update):
            return event.message or event.callback_query
        return None

    async def _is_payment_flow_event(
        self,
        event: TelegramObject,
        data: dict[str, Any],
        user: User,
    ) -> bool:
        # Only company staff can continue through the payment flow while blocked.
        if user.role not in (UserRole.agent, UserRole.director):
            return False

        effective_event = self._message_or_callback(event)

        if isinstance(effective_event, CallbackQuery):
            callback_data = effective_event.data or ""
            return (
                callback_data == "pay_start"
                or callback_data == "pay_cancel"
                or callback_data.startswith("pay_method:")
                or callback_data.startswith("pay_invoice_method:")
            )

        if isinstance(effective_event, Message):
            state: FSMContext | None = data.get("state")
            if state is not None:
                return await state.get_state() == PaymentStates.waiting_proof.state

        return False

    async def _send_blocked_notice(self, event: TelegramObject, user: User) -> None:
        effective_event = self._message_or_callback(event)
        if effective_event is None:
            return

        if user.role == UserRole.client:
            text = t("service_blocked_client")
            reply_markup = None
        else:
            text = t("subscription_payment_required")
            reply_markup = payment_method_kb()

        if isinstance(effective_event, Message):
            await effective_event.answer(text, reply_markup=reply_markup)
            return

        if effective_event.message:
            await effective_event.message.answer(text, reply_markup=reply_markup)
        await effective_event.answer()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("db_user")

        if user is None:
            return await handler(event, data)

        # Developer is global and never blocked by a company subscription.
        if user.role == UserRole.developer:
            return await handler(event, data)

        if user.role not in (UserRole.agent, UserRole.director):
            return await handler(event, data)

        if await self._is_payment_flow_event(event, data, user):
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
            await self._send_blocked_notice(event, user)
            return

        return await handler(event, data)
