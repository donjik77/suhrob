import time
from typing import Any, Awaitable, Callable

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

logger = structlog.get_logger()


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        start = time.monotonic()

        tg_user = None
        event_type = type(event).__name__

        if isinstance(event, Message):
            tg_user = event.from_user
            event_detail = event.text or event.content_type
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user
            event_detail = event.data
        else:
            event_detail = ""

        user_id = tg_user.id if tg_user else None

        try:
            result = await handler(event, data)
            elapsed = (time.monotonic() - start) * 1000
            logger.info(
                "event_handled",
                event_type=event_type,
                user_id=user_id,
                detail=event_detail,
                elapsed_ms=round(elapsed, 1),
            )
            return result
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            logger.error(
                "event_error",
                event_type=event_type,
                user_id=user_id,
                detail=event_detail,
                elapsed_ms=round(elapsed, 1),
                error=str(exc),
                exc_info=True,
            )
            raise
