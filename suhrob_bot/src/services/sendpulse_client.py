"""
src/services/sendpulse_client.py

Прямой клиент SendPulse API (OAuth client_credentials) — проактивная
отправка сообщений и фото Instagram-контактам в обход /webhook/smmbot.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ ОТ Salebot: /webhook/smmbot — синхронный роут,
отвечает ТОЛЬКО внутри входящего запроса SendPulse (ответ = поле "reply").
Он не годится для:
  - реальной отправки фото (SendPulse-флоу не умеет разворачивать массив
    URL из JSON-ответа в отдельные вложения — это отдельные вызовы API);
  - джобов планировщика (follow-up, property alerts) — они стартуют сами
    по расписанию, вне какого-либо входящего запроса от SendPulse.

Both cases go through this module's send_sendpulse_message/_image, which
push messages via SendPulse's outbound chatbot API using a cached OAuth
token.
"""

import time

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger()

SENDPULSE_API_BASE = "https://api.sendpulse.com"
SENDPULSE_TOKEN_URL = f"{SENDPULSE_API_BASE}/oauth/access_token"
SENDPULSE_SEND_URL = f"{SENDPULSE_API_BASE}/instagram/contacts/send"
SENDPULSE_BOTS_URL = f"{SENDPULSE_API_BASE}/chatbots/bots"

# Токен живёт 60 минут по документации SendPulse — кешируем на 55, чтобы
# не ловить протухание токена посреди отправки.
_TOKEN_TTL_SECONDS = 55 * 60

_token_cache: dict[str, float | str] = {"token": "", "expires_at": 0.0}


async def get_sendpulse_token() -> str | None:
    """
    Возвращает закешированный access_token, обновляя его по истечении TTL.
    None, если SENDPULSE_API_ID/SECRET не заданы или запрос упал.
    """
    if not settings.SENDPULSE_API_ID or not settings.SENDPULSE_API_SECRET:
        logger.error("sendpulse_credentials_missing",
                     hint="Задай SENDPULSE_API_ID и SENDPULSE_API_SECRET в Railway Variables")
        return None

    now = time.monotonic()
    if _token_cache["token"] and now < float(_token_cache["expires_at"]):
        return str(_token_cache["token"])

    payload = {
        "grant_type": "client_credentials",
        "client_id": settings.SENDPULSE_API_ID,
        "client_secret": settings.SENDPULSE_API_SECRET,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(SENDPULSE_TOKEN_URL, json=payload)
        if resp.status_code != 200:
            logger.error("sendpulse_token_failed", status=resp.status_code,
                         body=resp.text[:300])
            return None
        data = resp.json()
        token = data.get("access_token")
        if not token:
            logger.error("sendpulse_token_no_access_token", body=str(data)[:300])
            return None
        _token_cache["token"] = token
        _token_cache["expires_at"] = now + _TOKEN_TTL_SECONDS
        return token
    except Exception as exc:
        logger.error("sendpulse_token_exception", error=str(exc))
        return None


async def _send(payload: dict) -> bool:
    """Общий POST на /instagram/contacts/send с авторизацией."""
    token = await get_sendpulse_token()
    if not token:
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                SENDPULSE_SEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.error("sendpulse_send_failed", status=resp.status_code,
                         body=resp.text[:300], contact=payload.get("contact_id"))
            return False
        body = resp.json() if resp.content else {}
        if isinstance(body, dict) and body.get("success") is False:
            logger.error("sendpulse_send_error", body=str(body)[:300],
                         contact=payload.get("contact_id"))
            return False
        return True
    except Exception as exc:
        logger.error("sendpulse_send_exception", error=str(exc),
                     contact=payload.get("contact_id"))
        return False


async def send_sendpulse_message(contact_id: str, text: str) -> bool:
    """Текстовое сообщение контакту SendPulse (Instagram)."""
    if not contact_id or not text:
        return True
    payload = {
        "contact_id": str(contact_id),
        "messages": [{"type": "text", "message": {"text": text}}],
    }
    return await _send(payload)


async def send_sendpulse_image(contact_id: str, image_url: str) -> bool:
    """Одна картинка контакту SendPulse (Instagram), по публичному URL."""
    if not contact_id or not image_url:
        return True
    payload = {
        "contact_id": str(contact_id),
        "messages": [{
            "type": "image",
            "message": {
                "attachment": {
                    "type": "image",
                    "payload": {"url": image_url},
                }
            },
        }],
    }
    return await _send(payload)


async def list_sendpulse_bots() -> list[dict] | None:
    """
    GET /chatbots/bots — список ботов аккаунта. Разовый вызов для того,
    чтобы найти bot_id Instagram-бота и прописать его в SENDPULSE_BOT_ID.
    Не используется в горячем пути отправки.
    """
    token = await get_sendpulse_token()
    if not token:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.get(
                SENDPULSE_BOTS_URL,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            logger.error("sendpulse_bots_failed", status=resp.status_code,
                         body=resp.text[:300])
            return None
        data = resp.json()
        return data if isinstance(data, list) else data.get("data")
    except Exception as exc:
        logger.error("sendpulse_bots_exception", error=str(exc))
        return None
