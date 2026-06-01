from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware
from aiogram.enums import ChatMemberStatus
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from src.bot.keyboards.channel import build_required_subscription_kb
from src.config import settings
from src.db.models import User, UserRole

logger = structlog.get_logger()


class ChannelSubscriptionMiddleware(BaseMiddleware):
    """Require users to join the public Telegram channel before using the bot."""

    _ACTIVE_STATUSES = {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
    }

    def __init__(
        self,
        *,
        channel_id: str | None = None,
        channel_url: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.channel_id = channel_id or settings.REQUIRED_CHANNEL_ID
        self.channel_url = channel_url or settings.REQUIRED_CHANNEL_URL
        self.enabled = settings.REQUIRE_CHANNEL_SUBSCRIPTION if enabled is None else enabled

    def _event_user_id(self, event: TelegramObject) -> int | None:
        if isinstance(event, (Message, CallbackQuery)):
            return event.from_user.id if event.from_user else None
        if isinstance(event, Update):
            if event.message and event.message.from_user:
                return event.message.from_user.id
            if event.callback_query and event.callback_query.from_user:
                return event.callback_query.from_user.id
        return None

    def _message_or_callback(self, event: TelegramObject) -> Message | CallbackQuery | None:
        if isinstance(event, (Message, CallbackQuery)):
            return event
        if isinstance(event, Update):
            return event.message or event.callback_query
        return None

    async def _is_subscribed(self, event: Message | CallbackQuery, user_id: int) -> bool:
        member = await event.bot.get_chat_member(self.channel_id, user_id)
        if member.status in self._ACTIVE_STATUSES:
            return True
        if member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False):
            return True
        return False

    async def _send_required_message(self, event: Message | CallbackQuery) -> None:
        text = (
            "Botdan foydalanish uchun avval kanalga obuna bo'ling.\n\n"
            "Obuna bo'lgach, tekshirish tugmasini bosing."
        )
        reply_markup = build_required_subscription_kb(self.channel_url)

        if isinstance(event, Message):
            await event.answer(text, reply_markup=reply_markup)
            return

        if event.message:
            await event.message.answer(text, reply_markup=reply_markup)
        await event.answer("Avval kanalga obuna bo'ling.", show_alert=True)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.enabled or not self.channel_id:
            return await handler(event, data)

        user: User | None = data.get("db_user")
        if user is None or user.role == UserRole.developer:
            return await handler(event, data)

        effective_event = self._message_or_callback(event)
        if effective_event is None:
            return await handler(event, data)

        user_id = self._event_user_id(event)
        if user_id is None:
            return await handler(event, data)

        try:
            if await self._is_subscribed(effective_event, user_id):
                return await handler(event, data)
        except Exception as exc:
            logger.warning(
                "required_channel_subscription_check_failed",
                channel_id=self.channel_id,
                user_id=user_id,
                error=str(exc),
            )

        await self._send_required_message(effective_event)
        return None
