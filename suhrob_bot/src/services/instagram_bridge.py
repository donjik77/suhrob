"""
src/services/instagram_bridge.py

Мост между Salebot (Instagram Direct) и AI-логикой Telegram-бота.

ПЕРЕЕЗД С MANYCHAT НА SALEBOT
-----------------------------
Архитектура прежняя: входящее сообщение → наш Railway → мгновенный ACK →
фоновая задача (AI) → ответ обратно через API конструктора. Поменялся только
провайдер, а значит:
  • разбор входящего вебхука — у Salebot своя схема (client.id, is_input, ...);
  • отправка — POST https://chatter.salebot.pro/api/{KEY}/message вместо
    ManyChat sendContent;
  • вложения — attachment_type/attachment_url вместо ManyChat-блоков;
  • кнопки — buttons вместо quick_replies.

ID-СХЕМА В БАЗЕ НЕ МЕНЯЕТСЯ: Instagram-клиент по-прежнему живёт в users с
ОТРИЦАТЕЛЬНЫМ telegram_user_id, только теперь это -abs(salebot_client_id).
Вся логика, завязанная на "отрицательный id = не-Telegram клиент"
(уведомления агенту, джобы планировщика), продолжает работать как есть.

ОТЛИЧИЕ РЕНДЕРА ОТ TELEGRAM
---------------------------
В Telegram объект показывается карточкой ([CARD:ID] → фото + подпись).
В Instagram карточек НЕТ: модель отдаёт сжатый текст по вариантам, а мост
отдельным сообщением спрашивает "показать фото?". Фото уходят только после
явного согласия клиента (см. _PENDING_PHOTOS).
"""

import asyncio
import re

import httpx
import structlog
from aiohttp import web
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from src.config import settings
from src.db.session import AsyncSessionFactory
from src.db.models import (
    User, UserRole, Company, ClientProfile, ClientConversation,
    Property, PropertyMedia, PropertyStatus, FileType,
    LeadAssignment, LeadStatus,
)
from src.services import ai_service
from src.services.ai_service import chat_with_client

logger = structlog.get_logger()

# ------------------------------------------------------------------ #
#  Настройки
# ------------------------------------------------------------------ #

# Публичный адрес Railway-сервиса. ОБЯЗАТЕЛЬНО задать в переменных окружения,
# иначе Instagram не сможет скачать фото по attachment_url.
# Пример: https://suhrob-production.up.railway.app
PUBLIC_BASE_URL = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")

# АСИНХРОННАЯ СХЕМА: мы не отвечаем контентом внутри HTTP-запроса Salebot.
# Вебхук возвращает мгновенный ack, готовый ответ уходит отдельным вызовом
# API. Поэтому AI может думать сколько нужно.
AI_TIMEOUT_SECONDS = 30

# Ключ API Salebot: настройки проекта → API. В Railway Variables — SALEBOT_API_KEY.
SALEBOT_API_KEY = (getattr(settings, "SALEBOT_API_KEY", "") or "").strip()
SALEBOT_API_BASE = "https://chatter.salebot.pro/api"

# client_type Salebot для Instagram. Если на проект подключат ещё WhatsApp или
# Telegram, их сообщения придут на тот же вебхук — фильтр не даёт перепутать
# канал. 0 в настройках = не проверять.
SALEBOT_IG_CLIENT_TYPE = int(getattr(settings, "SALEBOT_INSTAGRAM_CLIENT_TYPE", 6) or 0)

# Сколько объектов максимум показываем за один ответ и сколько фото на объект.
MAX_CARDS_PER_REPLY = 2
MAX_PHOTOS_PER_PROPERTY = 4

# Версия моста — видна в GET /health. По ней проверяем, что Railway запустил
# свежий код, а не кэшированную сборку.
BRIDGE_VERSION = "2026-07-26-salebot-v1"

# Максимальная длина одного текстового сообщения в Instagram DM.
IG_TEXT_LIMIT = 950

# ID компании, к которой относится Instagram-аккаунт.
# Если не задан — берём первую активную компанию.
INSTAGRAM_COMPANY_ID = getattr(settings, "INSTAGRAM_COMPANY_ID", None)


# ------------------------------------------------------------------ #
#  Регулярки
# ------------------------------------------------------------------ #

_CARD_MARKER_RE = re.compile(r"\[CARD\s*:\s*(\d+)\]", re.IGNORECASE)
_VISIBLE_PROPERTY_ID_RE = re.compile(r"(?:CARD_)?(?:#\s*)?ID[_:\-\s]*(\d+)", re.IGNORECASE)

# Сообщение целиком из одного номера.
_PHONE_RE = re.compile(r"^\+?\d[\d\s().\-]{6,}$")
# Телефон ВНУТРИ длинного сообщения ("mening raqamim +998901234567").
_PHONE_ANYWHERE_RE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")
# Если в сообщении речь о деньгах — цифры почти наверняка цена, не телефон.
_CURRENCY_HINT_RE = re.compile(
    r"(so'?m|sum|сум|dollar|дол|\$|ming|mln|million|byudjet|narx)",
    re.IGNORECASE,
)
# Коды мобильных операторов Узбекистана. Нужны для номера БЕЗ префикса +998:
# без этой проверки бюджет "100 000 000" (9 цифр, без слова "so'm") проходил
# как телефон "+998100000000" — сообщение уходило в ветку приёма номера, AI
# не вызывался вовсе, и клиент вместо ответа получал "Rahmat, agent
# bog'lanadi". Это и был обрыв цепочки из п.5 ТЗ.
_UZ_MOBILE_CODES = {
    "33", "50", "55", "77", "88", "90", "91", "93", "94", "95", "97", "98", "99",
}

# Триггеры "хочу агента". Прежний список ловил только несколько книжных слов,
# а узбекские клиенты пишут иначе — "qo'ng'iroq qiling", "raqamingiz bormi",
# "gaplashsam bo'ladimi", "kelib ko'rsam", по-русски "позвоните", "риелтор".
# Из-за узкого паттерна цепочка "хочу агента → запрос номера" часто просто
# не запускалась.
_AGENT_CONNECT_RE = re.compile(
    r"(agent|makler|rieltor|rialtor|broker|menejer|mutaxassis"
    r"|bog'?la|boglan|bog'lan|aloqa|kontakt|murojaat"
    r"|telefon|raqam|nomer|qo'?ng'?iroq|qongiroq|zvonok"
    r"|gaplash|suhbatlash|uchrash|ko'?rish|korish|kelsam|kelib"
    r"|агент|риелтор|риэлтор|маклер|менеджер|позвон|звонит|связ|контакт"
    r"|телефон|номер|встрет|посмотрет)",
    re.IGNORECASE,
)

# Согласие на показ фото. В Instagram фото уходят ТОЛЬКО после явного "да".
_AFFIRM_RE = re.compile(
    r"^\W*("
    r"ha+|xa+|mayli|ok+|okey|okay|yes|bo'?ladi|boladi|albatta|zo'?r"
    r"|ko'?rsat\w*|korsat\w*|yubor\w*|rasm\w*|foto\w*|surat\w*"
    r"|да|ага|давай|хорошо|конечно|покажи\w*|можно|\+"
    r")\W*$",
    re.IGNORECASE,
)

QUALIFY_SCORE_THRESHOLD = 70

# Пол приходит только в первом сообщении из фло — держим на весь диалог.
_contact_gender: dict[str, str] = {}

# Объекты, по которым мы предложили клиенту фото и ждём "да". Ровно тот же
# паттерн "ждём ответ клиента на предыдущий вопрос", что и приём номера.
_PENDING_PHOTOS: dict[str, list[int]] = {}


def find_phone_in_text(text: str) -> str | None:
    """
    Ищет телефон и в сообщении из одного номера, и внутри фразы.
    Возвращает нормализованный номер (+998...) или None.
    """
    text = (text or "").strip()
    candidate = None
    if _PHONE_RE.match(text):
        candidate = text
    elif not _CURRENCY_HINT_RE.search(text):
        m = _PHONE_ANYWHERE_RE.search(text)
        if m:
            candidate = m.group()

    if not candidate:
        return None

    digits = re.sub(r"\D", "", candidate)

    if len(digits) == 9:
        # Локальная запись без кода страны. Принимаем ТОЛЬКО если начинается
        # с реального кода оператора — иначе сюда попадают суммы в сумах.
        if digits[:2] not in _UZ_MOBILE_CODES:
            return None
        digits = "998" + digits
    elif len(digits) == 12 and digits.startswith("998"):
        pass
    elif not (11 <= len(digits) <= 15):
        return None

    return f"+{digits}"


def clean_ai_reply(reply: str) -> str:
    """Вырезает строки с маркерами, чтобы клиент не видел [CARD:162]."""
    lines = []
    for line in (reply or "").splitlines():
        if _CARD_MARKER_RE.search(line) or _VISIBLE_PROPERTY_ID_RE.search(line):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or "Mos variantlarni tayyorlayapman."


def wants_photos(text: str) -> bool:
    """Клиент согласился посмотреть фото."""
    return bool(_AFFIRM_RE.match((text or "").strip()))


def mentions_property(text: str) -> bool:
    """В ответе модели есть похожее на вариант: цена или количество комнат."""
    return bool(re.search(r"(\$\s*\d|\d\s*xona)", text or "", re.IGNORECASE))


def asks_about_photos(text: str) -> bool:
    """Модель сама спросила про фото — второй такой вопрос не нужен."""
    return bool(re.search(r"(rasm|surat|foto)", text or "", re.IGNORECASE))


# ------------------------------------------------------------------ #
#  Salebot API: разбор входящего и отправка исходящего
# ------------------------------------------------------------------ #

def parse_salebot_update(data: dict) -> dict | None:
    """
    Разбирает тело вебхука Salebot.

    Salebot шлёт на webhook проекта КАЖДОЕ сообщение — и входящее от клиента,
    и исходящее наше. Обрабатываем только is_input == 1, иначе бот начнёт
    отвечать на собственное эхо и уйдёт в цикл.

    Возвращает {"client_id", "message", "first_name", "gender"} либо None,
    если сообщение не наше (эхо, чужой канал, нет client.id).
    """
    if not isinstance(data, dict):
        return None

    client = data.get("client")
    if isinstance(client, dict):
        # Нативный формат Salebot
        if int(data.get("is_input") or 0) != 1:
            return None  # эхо нашего же ответа
        if SALEBOT_IG_CLIENT_TYPE:
            ctype = client.get("client_type")
            if ctype is not None and int(ctype) != SALEBOT_IG_CLIENT_TYPE:
                logger.info("salebot_skip_other_channel", client_type=ctype)
                return None
        raw_id = client.get("id")
        first_name = client.get("name")
        gender = ""
    else:
        # Плоское тело: ручной вызов из фло Salebot или наши /phone, /followup.
        raw_id = data.get("client_id") or data.get("user_id")
        first_name = data.get("first_name") or data.get("name")
        gender = (data.get("gender") or "").lower()

    if raw_id in (None, ""):
        return None
    try:
        client_id = int(raw_id)
    except (TypeError, ValueError):
        logger.warning("salebot_bad_client_id", raw=str(raw_id)[:50])
        return None

    return {
        "client_id": client_id,
        "message": (data.get("message") or "").strip(),
        "first_name": first_name,
        "gender": gender,
    }


async def send_salebot_message(
    client_id: int | str,
    text: str | None = None,
    attachment_url: str | None = None,
    buttons: list[str] | None = None,
) -> bool:
    """
    Одно сообщение клиенту через Salebot.

    buttons — список подписей reply-кнопок; разворачивается в формат Salebot
    {"buttons": {"hint": ..., "buttons": [{"type": "reply", ...}]}}.
    Используется и мостом, и планировщиком (напоминания в Instagram).
    """
    if not SALEBOT_API_KEY:
        logger.error("salebot_key_missing",
                     hint="Задай SALEBOT_API_KEY в Railway Variables")
        return False

    payload: dict = {"client_id": int(client_id)}
    if text:
        payload["message"] = text[:IG_TEXT_LIMIT]
    if attachment_url:
        payload["attachment_type"] = "image"
        payload["attachment_url"] = attachment_url
    if buttons:
        payload["buttons"] = {
            "hint": " / ".join(buttons)[:60],
            "buttons": [
                {"type": "reply", "text": label, "line": 0, "index_in_line": idx}
                for idx, label in enumerate(buttons[:11])
            ],
        }

    if len(payload) == 1:  # нечего слать
        return True

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{SALEBOT_API_BASE}/{SALEBOT_API_KEY}/message",
                json=payload,
            )
        if resp.status_code != 200:
            logger.error("salebot_send_failed", client=client_id,
                         status=resp.status_code, body=resp.text[:300])
            return False
        body = resp.json() if resp.content else {}
        if isinstance(body, dict) and body.get("error"):
            logger.error("salebot_send_error", client=client_id,
                         body=str(body)[:300])
            return False
        return True
    except Exception as exc:
        logger.error("salebot_send_exception", client=client_id, error=str(exc))
        return False


async def send_salebot_blocks(client_id: int | str, blocks: list[dict]) -> bool:
    """
    Последовательная отправка нескольких сообщений с паузами.

    block = {"text": ..., "attachment_url": ..., "buttons": [...]}

    Пауза между блоками сохранена с ManyChat-версии и по той же причине:
    Instagram доставляет текст мгновенно, а картинку — только после того, как
    Meta скачает её с нашего сервера. Без паузы фото "убегает" к соседнему
    объекту и сообщения перемешиваются. После блока с фото ждём дольше.
    """
    blocks = [b for b in (blocks or []) if b.get("text") or b.get("attachment_url")]
    if not blocks:
        return True

    ok_all = True
    for idx, block in enumerate(blocks):
        sent = await send_salebot_message(
            client_id,
            text=block.get("text"),
            attachment_url=block.get("attachment_url"),
            buttons=block.get("buttons"),
        )
        ok_all = ok_all and sent
        if idx != len(blocks) - 1:
            await asyncio.sleep(2.5 if block.get("attachment_url") else 0.8)
    return ok_all


def ack_response() -> web.Response:
    """Мгновенный ACK для Salebot: контент уйдёт отдельным вызовом API."""
    return web.json_response({"status": "ok"})


# ------------------------------------------------------------------ #
#  Пользователь Instagram внутри существующей таблицы users
# ------------------------------------------------------------------ #

async def resolve_company_id(session) -> int | None:
    if INSTAGRAM_COMPANY_ID:
        return int(INSTAGRAM_COMPANY_ID)
    company = (
        await session.execute(
            select(Company).where(Company.is_active == True).limit(1)  # noqa: E712
        )
    ).scalar_one_or_none()
    return company.id if company else None


async def get_or_create_ig_user(session, contact_id: str | int,
                                first_name: str | None) -> User:
    """
    В таблице users ключ — telegram_user_id. Чтобы не делать миграцию,
    Instagram-контакты пишем с ОТРИЦАТЕЛЬНЫМ id: -abs(salebot_client_id).
    Telegram никогда не выдаёт отрицательные user_id, коллизий не будет.
    """
    synthetic_id = -abs(int(contact_id))

    user = (
        await session.execute(
            select(User).where(User.telegram_user_id == synthetic_id)
        )
    ).scalar_one_or_none()

    if user:
        return user

    company_id = await resolve_company_id(session)
    user = User(
        telegram_user_id=synthetic_id,
        username=f"ig_{abs(int(contact_id))}",
        full_name=first_name or "Instagram mijoz",
        role=UserRole.client,
        company_id=company_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("ig_user_created", contact_id=contact_id, user_id=user.id)
    return user


# ------------------------------------------------------------------ #
#  Фото объектов — уходят ТОЛЬКО по явному согласию клиента
# ------------------------------------------------------------------ #

async def build_photo_blocks(session, company_id: int | None,
                             property_ids: list[int]) -> list[dict]:
    """
    Собирает блоки с фото по списку ID.

    Карточки как в Telegram здесь НЕ строятся: описание клиент уже получил
    текстом в предыдущем ответе. Тут короткая строка-подпись и сами фото.
    """
    if not company_id or not property_ids:
        return []

    result = await session.execute(
        select(Property)
        .where(
            Property.company_id == company_id,
            Property.status == PropertyStatus.active,
            Property.id.in_(property_ids),
        )
        .options(selectinload(Property.media))
    )
    props_by_id = {p.id: p for p in result.scalars().all()}
    props = [props_by_id[pid] for pid in property_ids if pid in props_by_id]
    props = props[:MAX_CARDS_PER_REPLY]

    if not props:
        return []

    await session.execute(
        update(Property)
        .where(Property.id.in_([p.id for p in props]))
        .values(views_count=Property.views_count + 1)
    )
    await session.commit()

    blocks: list[dict] = []
    photo_ids: list[int] = []

    for prop in props:
        photos = [
            m for m in (prop.media or [])
            if getattr(m.file_type, "value", m.file_type) == FileType.photo.value
        ][:MAX_PHOTOS_PER_PROPERTY]

        if not photos or not PUBLIC_BASE_URL:
            # Логируем причину: либо у объекта нет фото, либо не задан
            # PUBLIC_BASE_URL. Без этого непонятно, баг это или данные.
            logger.warning(
                "ig_no_photo_for_property",
                property_id=prop.id,
                media_count=len(prop.media or []),
                has_public_base_url=bool(PUBLIC_BASE_URL),
            )
            continue

        # Короткая подпись — деловой тон Instagram, без карточки.
        price = f"{float(prop.price_usd):,.0f}".replace(",", " ")
        blocks.append({
            "text": f"{prop.location_district}, {prop.rooms} xona, ${price}"
        })
        for photo in photos:
            # .jpg в конце обязателен: Instagram может не принять URL
            # картинки без расширения файла
            blocks.append({
                "attachment_url": f"{PUBLIC_BASE_URL}/media/{photo.id}.jpg"
            })
            photo_ids.append(photo.id)

    # ПРЕДПРОГРЕВ: скачиваем фото из Telegram в кэш ДО отправки, чтобы Meta
    # забрала их с нашего сервера мгновенно и порядок не сломался.
    await prefetch_media(photo_ids)

    return blocks


# ------------------------------------------------------------------ #
#  Прокси для фото: Telegram file_id -> публичный HTTPS-URL
# ------------------------------------------------------------------ #

_file_path_cache: dict[int, str] = {}

# Кэш САМИХ БАЙТОВ фото. Критично для порядка сообщений: Instagram доставляет
# фото клиенту только после того, как скачает его с нашего сервера. Если при
# этом мы ходим в Telegram (1-3 сек на фото) — фото опаздывают.
_media_bytes_cache: dict[int, tuple[bytes, str]] = {}
_MEDIA_CACHE_MAX = 80


def _cache_media_bytes(media_id: int, body: bytes, content_type: str) -> None:
    if len(_media_bytes_cache) >= _MEDIA_CACHE_MAX:
        # Простое вытеснение самого старого элемента
        _media_bytes_cache.pop(next(iter(_media_bytes_cache)), None)
    _media_bytes_cache[media_id] = (body, content_type)


async def _download_media_bytes(media_id: int) -> tuple[bytes, str] | None:
    """
    Скачивает фото из Telegram по media_id и кладёт в кэш.
    Возвращает (байты, content_type) или None при ошибке.
    """
    cached = _media_bytes_cache.get(media_id)
    if cached:
        return cached

    async with AsyncSessionFactory() as session:
        media = (
            await session.execute(
                select(PropertyMedia)
                .where(PropertyMedia.id == media_id)
                .options(selectinload(PropertyMedia.property))
            )
        ).scalar_one_or_none()
        if not media:
            return None
        company = (
            await session.execute(
                select(Company).where(Company.id == media.property.company_id)
            )
        ).scalar_one_or_none()

    if not company or not company.bot_token:
        return None
    token = company.bot_token

    try:
        async with httpx.AsyncClient(timeout=20) as http:
            file_path = _file_path_cache.get(media_id)
            if not file_path:
                r = await http.get(
                    f"https://api.telegram.org/bot{token}/getFile",
                    params={"file_id": media.file_id},
                )
                data = r.json()
                if not data.get("ok"):
                    logger.warning("getfile_failed", media_id=media_id, resp=data)
                    return None
                file_path = data["result"]["file_path"]
                _file_path_cache[media_id] = file_path

            file_resp = await http.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}"
            )
            if file_resp.status_code != 200:
                _file_path_cache.pop(media_id, None)
                return None

            content_type = "image/jpeg"
            if file_path.lower().endswith(".png"):
                content_type = "image/png"

            _cache_media_bytes(media_id, file_resp.content, content_type)
            return file_resp.content, content_type
    except Exception as exc:
        logger.error("media_download_error", media_id=media_id, error=str(exc))
        return None


async def prefetch_media(media_ids: list[int]) -> None:
    """Параллельно прогревает кэш фото ДО отправки клиенту."""
    if not media_ids:
        return
    try:
        await asyncio.wait_for(
            asyncio.gather(
                *(_download_media_bytes(mid) for mid in media_ids),
                return_exceptions=True,
            ),
            timeout=12,
        )
        logger.info("media_prefetched", count=len(media_ids))
    except asyncio.TimeoutError:
        logger.warning("media_prefetch_timeout", count=len(media_ids))


async def media_proxy(request: web.Request) -> web.Response:
    """
    GET /media/<media_id>
    Отдаёт байты фото наружу. Сначала смотрит кэш — после предпрогрева
    ответ мгновенный.
    """
    try:
        raw_id = request.match_info["media_id"]
        # Принимаем и "455", и "455.jpg" — расширение отбрасываем
        media_id = int(raw_id.split(".")[0])
    except (KeyError, ValueError):
        return web.Response(status=400, text="bad media id")

    result = await _download_media_bytes(media_id)
    if not result:
        return web.Response(status=404, text="not found")

    body, content_type = result
    return web.Response(
        body=body,
        content_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ------------------------------------------------------------------ #
#  Основной обработчик сообщений из Instagram
# ------------------------------------------------------------------ #

async def _run_ai(user_message: str, history: list[dict], client_profile: dict,
                  company_id: int) -> str:
    async with AsyncSessionFactory() as ai_session:
        return await chat_with_client(
            user_message=user_message,
            conversation_history=history,
            client_profile=client_profile,
            company_id=company_id or 0,
            session=ai_session,
            property_id=None,
            channel="instagram",
        )


async def instagram_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/instagram

    Тело — нативный формат Salebot (проект шлёт сюда каждое сообщение):
    {
      "id": "...",
      "client": {"id": 123, "recepient": "<ig_user_id>", "client_type": 6,
                 "name": "...", "avatar": "...", "created_at": "...",
                 "tag": "...", "group": "..."},
      "message": "текст", "attachments": [...],
      "message_id": 45, "project_id": 1,
      "is_input": 1, "delivered": 1, "error_message": ""
    }

    Плоское тело {"client_id"/"user_id", "message", ...} тоже принимается —
    им пользуются ручные вызовы из фло.
    """
    try:
        data = await request.json()
    except Exception:
        return ack_response()

    update_data = parse_salebot_update(data)
    if not update_data:
        # Эхо нашего ответа, чужой канал или битый client.id — молча ок.
        return ack_response()

    contact_id = str(update_data["client_id"])
    user_message = update_data["message"]

    if not user_message:
        # Стикеры/реакции без текста. Раньше клиент получал холодное
        # приветствие — выглядело так, будто бот его не слышит.
        asyncio.create_task(send_salebot_message(
            contact_id, "Yozib yuboring — qanday uy kerak?"
        ))
        return ack_response()

    logger.info("ig_message_in", contact=contact_id, text=user_message[:100],
                is_input=data.get("is_input"))

    # Мгновенно подтверждаем приём, думаем и отвечаем в фоне через API.
    asyncio.create_task(_process_and_reply(
        contact_id, user_message,
        update_data["first_name"], update_data["gender"],
    ))
    return ack_response()


async def _process_and_reply(contact_id: str, user_message: str,
                             first_name: str | None, gender: str) -> None:
    """
    Вся тяжёлая работа — вне HTTP-запроса Salebot:
    пользователь -> история -> AI -> текст (без карточек) -> отправка.
    """
    # Пол приходит только с первым сообщением — кэшируем на весь диалог
    if gender in ("male", "female"):
        _contact_gender[contact_id] = gender
    else:
        gender = _contact_gender.get(contact_id, "")

    # 1. Клиент согласился посмотреть фото по предложенным вариантам.
    # Проверяем ДО AI: это ответ на наш предыдущий вопрос, а не новый запрос.
    pending = _PENDING_PHOTOS.get(contact_id)
    if pending and wants_photos(user_message):
        _PENDING_PHOTOS.pop(contact_id, None)
        async with AsyncSessionFactory() as session:
            user = await get_or_create_ig_user(session, contact_id, first_name)
            session.add(ClientConversation(
                user_id=user.id, property_id=None, role="user",
                message=user_message,
            ))
            await session.commit()
            blocks = await build_photo_blocks(session, user.company_id, pending)
        if blocks:
            await send_salebot_blocks(contact_id, blocks)
            logger.info("ig_photos_sent", contact=contact_id,
                        properties=len(pending))
        else:
            await send_salebot_message(contact_id, "Rasmlar hozircha yo'q.")
        return

    # 2. Пользователь + история + профиль
    async with AsyncSessionFactory() as session:
        user = await get_or_create_ig_user(session, contact_id, first_name)
        company_id = user.company_id
        user_id = user.id

        # Телефон, присланный текстом (отдельным сообщением ИЛИ внутри фразы
        # "mening raqamim +998...") — быстрая ветка без AI.
        phone_in_msg = find_phone_in_text(user_message) if not user.phone else None
        if phone_in_msg:
            # Сообщение с номером тоже пишем в историю: без этого следующий
            # запрос к AI не видел шага "клиент оставил номер", и бот просил
            # номер повторно.
            session.add(ClientConversation(
                user_id=user_id, property_id=None, role="user",
                message=user_message,
            ))
            await session.commit()
            reply_text = await _handle_phone_submission(session, user, phone_in_msg)
            session.add(ClientConversation(
                user_id=user_id, property_id=None, role="assistant",
                message=reply_text,
            ))
            await session.commit()
            await send_salebot_message(contact_id, reply_text)
            logger.info("ig_phone_captured", contact=contact_id, user_id=user_id)
            return

        history_rows = (
            await session.execute(
                select(ClientConversation)
                .where(ClientConversation.user_id == user_id)
                .order_by(ClientConversation.created_at.desc())
                .limit(12)
            )
        ).scalars().all()
        history = [{"role": r.role, "content": r.message} for r in reversed(history_rows)]

        session.add(ClientConversation(
            user_id=user_id, property_id=None, role="user", message=user_message,
        ))
        await session.commit()

        profile_row = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        # Тот же сборщик, что в Telegram — включает имя/пол/промокод из notes.
        client_profile = ai_service.profile_to_context(profile_row)

    # 3. Подсказка про пол, чтобы бот не сказал девушке "jigar".
    prompt_text = user_message
    if gender == "female":
        prompt_text += "\n[Kontekst: mijoz AYOL]"
    elif gender == "male":
        prompt_text += "\n[Kontekst: mijoz ERKAK]"

    # 4. Вызов AI — можно ждать по-настоящему (мы вне HTTP-запроса)
    try:
        raw_reply = await asyncio.wait_for(
            _run_ai(prompt_text, history, client_profile, company_id),
            timeout=AI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("ig_ai_timeout", contact=contact_id)
        await send_salebot_message(contact_id, "Biroz kuting, qaytadan yozing.")
        return
    except Exception as exc:
        logger.error("ig_ai_error", contact=contact_id, error=str(exc))
        await send_salebot_message(contact_id, "Texnik nosozlik. Qaytadan urining.")
        return

    # 5. РЕНДЕР ДЛЯ INSTAGRAM: карточек нет.
    # Промпт (INSTAGRAM_RULES) запрещает маркеры [CARD:ID], но если модель
    # всё же их вставила — вырезаем, клиент их видеть не должен.
    text_reply = clean_ai_reply(raw_reply)

    async with AsyncSessionFactory() as session:
        session.add(ClientConversation(
            user_id=user_id, property_id=None, role="assistant",
            message=text_reply,
        ))
        await session.commit()

        # Какие объекты покажем, если клиент попросит фото. Считаем сами тем
        # же поиском, что кормил модель, — не полагаемся на то, что модель
        # напечатала ID (в Instagram она их и не печатает).
        pending_ids = await _candidate_property_ids(
            session, company_id, user_message, history
        )

        fresh_user = await session.get(User, user_id)
        has_phone = bool(fresh_user and fresh_user.phone)

    wants_agent = bool(_AGENT_CONNECT_RE.search(user_message))
    should_ask_phone = wants_agent and not has_phone
    if wants_agent and has_phone:
        # Телефон уже есть, клиент просит агента — лид уходит агенту.
        # Раньше этот случай терялся и агента никто не уведомлял.
        asyncio.create_task(_notify_agent_with_profile(user_id))

    history_for_qualify = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": text_reply},
    ]
    asyncio.create_task(_qualify_in_background(user_id, history_for_qualify))

    blocks: list[dict] = [{"text": text_reply}]

    # Фото предлагаем ОТДЕЛЬНЫМ вопросом и только когда в ответе реально
    # есть варианты. Сами фото уйдут после "ha" (см. начало функции).
    if pending_ids and mentions_property(text_reply):
        _PENDING_PHOTOS[contact_id] = pending_ids
        if not asks_about_photos(text_reply):
            blocks.append({
                "text": "Rasmlarini ko'rasizmi?",
                "buttons": ["Ha", "Yo'q"],
            })

    if should_ask_phone:
        blocks.append({"text": "Telefon raqamingizni yozing (+998901234567)."})

    sent = await send_salebot_blocks(contact_id, blocks)
    logger.info("ig_message_out", contact=contact_id,
                pending_photos=len(pending_ids), asked_phone=should_ask_phone,
                sent=sent)


async def _candidate_property_ids(session, company_id: int | None,
                                  user_message: str,
                                  history: list[dict]) -> list[int]:
    """
    Объекты, о которых шла речь в этом ответе. Тот же поиск, что строит
    контекст для модели, поэтому список совпадает с тем, что она видела.
    """
    if not company_id:
        return []
    try:
        district = await ai_service.extract_district(
            user_message, history, company_id, session
        )
        price_max = ai_service.extract_price(user_message, history)
        rooms = ai_service.extract_rooms(user_message, history)
        props = await ai_service.search_properties(
            company_id, district, price_max, rooms, session,
            limit=MAX_CARDS_PER_REPLY,
        )
        return [p.id for p in props]
    except Exception as exc:
        logger.warning("ig_candidates_failed", error=str(exc))
        return []


async def _qualify_in_background(user_id: int, history: list[dict]) -> None:
    """
    Запускается через asyncio.create_task после ответа клиенту.
    Клиент уже получил сообщение, здесь обновляем профиль в БД.

    Вызывается после КАЖДОГО значимого сообщения клиента — так же, как в
    Telegram-пути. Именно здесь имя/пол/промокод попадают в
    client_profiles.notes и переживают окно истории диалога.
    """
    try:
        qualification = await asyncio.wait_for(
            ai_service.qualify_client(history), timeout=25
        )
    except asyncio.TimeoutError:
        logger.warning("ig_qualify_bg_timeout", user_id=user_id)
        return
    except Exception as exc:
        logger.warning("ig_qualify_bg_failed", user_id=user_id, error=str(exc))
        return

    try:
        async with AsyncSessionFactory() as session:
            await _upsert_profile(session, user_id, qualification)
    except Exception as exc:
        logger.warning("ig_qualify_bg_save_failed", user_id=user_id, error=str(exc))
        return

    # Горячий клиент (score >= 70, телефон уже есть) — уведомляем агента.
    # skip_if_lead_exists защищает от спама.
    if qualification.get("qualification_score", 0) >= QUALIFY_SCORE_THRESHOLD:
        await _notify_agent_with_profile(user_id, skip_if_lead_exists=True)


def _profile_qualification(profile: ClientProfile | None) -> dict:
    """Квалификация из уже накопленного профиля (для уведомления агента)."""
    # notes теперь JSON — резюме достаём через profile_summary, иначе агенту
    # прилетел бы сырой JSON вместо человеческого текста.
    summary = ai_service.profile_summary(profile.notes if profile else None)
    return {
        "qualification_score": (profile.qualification_score if profile else 0),
        "budget_min_usd": (profile.budget_min_usd if profile else None),
        "budget_max_usd": (profile.budget_max_usd if profile else None),
        "preferred_districts": (profile.preferred_districts if profile else []),
        "preferred_rooms": (profile.preferred_rooms if profile else []),
        "purchase_timeline": (profile.purchase_timeline if profile else None),
        "payment_method": (profile.payment_method if profile else None),
        "summary": summary or "Instagram orqali murojaat",
    }


async def _resolve_notifier_bot(session, company_id: int | None):
    """
    Возвращает (bot, нужно_ли_закрыть_сессию_бота).

    При пустом BotManager (например, платформа поднята на fallback BOT_TOKEN)
    собираем временный aiogram Bot из токена компании в БД — иначе лид молча
    пропадал.
    """
    bot = _get_notifier_bot(company_id)
    if bot is not None:
        return bot, False

    token = None
    if company_id:
        company = await session.get(Company, company_id)
        token = company.bot_token if company else None
    if not token:
        row = (
            await session.execute(
                select(Company).where(Company.bot_token != None).limit(1)  # noqa: E711
            )
        ).scalar_one_or_none()
        token = row.bot_token if row else None
    if not token:
        import os
        token = os.environ.get("BOT_TOKEN") or None
    if not token:
        return None, False

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)), True


async def _notify_agent_with_profile(user_id: int, *,
                                     skip_if_lead_exists: bool = False) -> None:
    """
    Уведомляет агента о лиде по данным профиля. Безопасна для фоновых
    задач: сама открывает сессию и глотает ошибки в лог.
    """
    from src.bot.handlers.client.ai_consultation import _maybe_assign_hot_lead

    try:
        async with AsyncSessionFactory() as session:
            user = await session.get(User, user_id)
            if not user or not user.phone:
                logger.warning("ig_lead_notify_no_phone", user_id=user_id)
                return

            if skip_if_lead_exists:
                existing = (
                    await session.execute(
                        select(LeadAssignment).where(
                            LeadAssignment.client_user_id == user.id,
                            LeadAssignment.status == LeadStatus.new,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    return

            profile = (
                await session.execute(
                    select(ClientProfile).where(ClientProfile.user_id == user.id)
                )
            ).scalar_one_or_none()

            bot, should_close = await _resolve_notifier_bot(session, user.company_id)
            if bot is None:
                logger.warning("ig_lead_notify_skipped_no_bot", user_id=user_id)
                return
            try:
                await _maybe_assign_hot_lead(
                    session, user, _profile_qualification(profile), bot,
                    client_phone=user.phone, property_id=None,
                )
                logger.info("ig_lead_notified", user_id=user_id)
            finally:
                if should_close:
                    await bot.session.close()
    except Exception as exc:
        logger.warning("ig_lead_notify_failed", user_id=user_id, error=str(exc))


async def _handle_phone_submission(session, user: User, phone: str) -> str:
    """
    Клиент прислал номер телефона. Сохраняем, квалифицируем по накопленному
    профилю и уведомляем агента — той же функцией, что использует
    Telegram-версия. Возвращает текст ответа клиенту.

    Оба пути приёма номера (обычное сообщение и отдельный шаг воронки
    /webhook/instagram/phone) сходятся здесь — раньше это были две разные
    ветки, и на одной из них уведомление агенту не уходило.
    """
    user.phone = phone
    await session.commit()

    await _notify_agent_with_profile(user.id)

    return "Rahmat! Agentimiz tez orada bog'lanadi."


async def _upsert_profile(session, user_id: int, data: dict) -> None:
    """Упрощённая версия _upsert_client_profile из ai_consultation.py."""
    from datetime import datetime, timezone

    existing = (
        await session.execute(
            select(ClientProfile).where(ClientProfile.user_id == user_id)
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    score = data.get("qualification_score", 0)

    if existing:
        for field in ("budget_min_usd", "budget_max_usd", "preferred_districts",
                      "preferred_rooms", "property_type", "purchase_timeline",
                      "payment_method"):
            if data.get(field):
                setattr(existing, field, data[field])
        existing.qualification_score = max(existing.qualification_score or 0, score)
        # Имя/пол/промокод колонок не имеют — merge_profile_notes кладёт их в
        # notes и не даёт затереть уже выданный промокод.
        existing.notes = ai_service.merge_profile_notes(existing.notes, data)
        existing.last_contact_at = now
    else:
        session.add(ClientProfile(
            user_id=user_id,
            budget_min_usd=data.get("budget_min_usd"),
            budget_max_usd=data.get("budget_max_usd"),
            preferred_districts=data.get("preferred_districts") or [],
            preferred_rooms=data.get("preferred_rooms") or [],
            property_type=data.get("property_type"),
            purchase_timeline=data.get("purchase_timeline"),
            payment_method=data.get("payment_method"),
            qualification_score=score,
            notes=ai_service.merge_profile_notes(None, data),
            last_contact_at=now,
        ))
    await session.commit()


# ------------------------------------------------------------------ #
#  Приём телефона отдельным шагом воронки Salebot
# ------------------------------------------------------------------ #

async def instagram_phone_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/instagram/phone
    Тело: {"client_id": 123, "phone": "+998901234567"}

    Вызывать из Salebot, если номер собирается отдельным шагом фло.
    Идёт через тот же _handle_phone_submission, что и номер из обычного
    сообщения, — чтобы два пути не разъезжались.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error"}, status=400)

    parsed = parse_salebot_update(data) or {}
    contact_id = parsed.get("client_id") or data.get("client_id") or data.get("user_id")
    phone = (data.get("phone") or data.get("message") or "").strip()

    if not contact_id or not phone:
        return web.json_response(
            {"status": "error", "reason": "no client_id or phone"}, status=400
        )

    normalized = find_phone_in_text(phone) or phone

    async with AsyncSessionFactory() as session:
        user = await get_or_create_ig_user(session, contact_id, None)
        reply = await _handle_phone_submission(session, user, normalized)

    await send_salebot_message(contact_id, reply)
    return web.json_response({"status": "ok"})


# ------------------------------------------------------------------ #
#  Follow-up: ответы клиента на напоминания планировщика
# ------------------------------------------------------------------ #

_FOLLOWUP_STOP_RE = re.compile(
    r"(topdim|topildi|kerak\s*emas|yozmang|bezovta|obuna"
    r"|нашел|нашёл|не\s*нужно|отпис|не\s*пиши)",
    re.IGNORECASE,
)
_FOLLOWUP_YES_RE = re.compile(
    r"(ha\b|xa\b|qidiryapman|izlayapman|davom|да\b|ищу)", re.IGNORECASE
)


async def instagram_followup_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/instagram/followup

    Instagram-эквивалент callback-обработчика followup:yes/no/unsub/found из
    Telegram: инлайн-кнопок в Instagram нет, поэтому ответ приходит текстом
    (нажатие reply-кнопки Salebot тоже приходит текстом).
    Тело — обычный апдейт Salebot либо {"client_id": 123, "answer": "..."}.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error"}, status=400)

    parsed = parse_salebot_update(data) or {}
    contact_id = parsed.get("client_id") or data.get("client_id") or data.get("user_id")
    answer = (data.get("answer") or parsed.get("message") or "").strip()
    if not contact_id:
        return web.json_response({"status": "error"}, status=400)

    async with AsyncSessionFactory() as session:
        user = (
            await session.execute(
                select(User).where(User.telegram_user_id == -abs(int(contact_id)))
            )
        ).scalar_one_or_none()
        if not user:
            return web.json_response({"status": "ok", "reason": "unknown client"})

        profile = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == user.id)
            )
        ).scalar_one_or_none()
        if not profile:
            return web.json_response({"status": "ok", "reason": "no profile"})

        if _FOLLOWUP_STOP_RE.search(answer):
            profile.unsubscribed = True
            reply = "Tushunarli, bezovta qilmaymiz. Omad!"
        elif _FOLLOWUP_YES_RE.search(answer):
            from datetime import datetime, timezone
            profile.last_contact_at = datetime.now(timezone.utc)
            reply = "Yaxshi. Qaysi tuman va byudjet?"
        else:
            reply = "Uy qidiryapsizmi? Ha yoki yo'q deb yozing."
        await session.commit()

    await send_salebot_message(contact_id, reply)
    return web.json_response({"status": "ok"})


# ------------------------------------------------------------------ #
#  SMMBOT: СИНХРОННЫЙ роут
# ------------------------------------------------------------------ #
#
# Отличие от /webhook/instagram (Salebot): там схема асинхронная — мгновенный
# ACK, а ответ уходит отдельным вызовом API конструктора. SMMBOT работает
# наоборот: делает POST внутри сценария и ЖДЁТ ответ в том же запросе, после
# чего сам отправляет его клиенту в директ. Поэтому здесь мы держим запрос,
# пока думает модель, и возвращаем текст в теле.
#
# Из этого следуют два правила:
#   1. Отвечать ВСЕГДА 200 с полем reply (кроме отсутствующего client_id) —
#      иначе сценарий SMMBOT падает и клиент не получает ничего.
#   2. Держать жёсткий таймаут на AI: без него зависший вызов подвесил бы
#      сценарий на стороне SMMBOT.
#
# SALEBOT_API_KEY этому роуту не нужен — исходящих вызовов он не делает.

SMMBOT_AI_TIMEOUT_SECONDS = 45
SMMBOT_ERROR_REPLY = "Kechiring, xatolik yuz berdi. Qayta urinib ko'ring."


async def smmbot_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/smmbot

    Тело запроса:
        {"client_id": 12345, "message": "...", "client_name": "..."}
    Ответ:
        {"reply": "<текст для клиента>"}

    ID-схема та же, что у Salebot-моста: telegram_user_id = -abs(client_id),
    поэтому один и тот же Instagram-клиент виден джобам планировщика и
    уведомлениям агенту одинаково, каким бы конструктором он ни пришёл.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    if not isinstance(data, dict):
        return web.json_response({"error": "invalid body"}, status=400)

    # str().strip() перед int(): SMMBOT присылает client_id строкой, иногда
    # с пробелами. Если шаблон в сценарии не подставился, придёт литерал
    # "{{client_id}}" — int() на нём падает, и мы обязаны ответить 400,
    # иначе завели бы мусорного пользователя с непредсказуемым id.
    try:
        client_id = int(str(data.get("client_id", "")).strip())
    except (TypeError, ValueError):
        logger.warning("smmbot_bad_client_id",
                       raw=str(data.get("client_id"))[:50])
        return web.json_response({"error": "client_id required"}, status=400)

    user_message = (data.get("message") or "").strip()
    client_name = data.get("client_name") or data.get("name")

    # Пустое сообщение (стикер, реакция) — молча отдаём пустой reply.
    # На пустую строку SMMBOT клиенту ничего не пошлёт.
    if not user_message:
        logger.info("smmbot_empty_message", client=client_id)
        return web.json_response({"reply": ""})

    logger.info("smmbot_message_in", client=client_id, text=user_message[:100])

    try:
        reply = await asyncio.wait_for(
            _smmbot_generate_reply(client_id, user_message, client_name),
            timeout=SMMBOT_AI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("smmbot_ai_timeout", client=client_id)
        return web.json_response({"reply": SMMBOT_ERROR_REPLY})
    except Exception as exc:
        logger.error("smmbot_failed", client=client_id, error=str(exc))
        return web.json_response({"reply": SMMBOT_ERROR_REPLY})

    logger.info("smmbot_message_out", client=client_id, length=len(reply))
    return web.json_response({"reply": reply})


async def _smmbot_generate_reply(client_id: int, user_message: str,
                                 client_name: str | None) -> str:
    """
    Пользователь -> история -> профиль -> AI -> сохранение.
    Вынесено отдельно, чтобы весь путь можно было ограничить одним wait_for.
    """
    async with AsyncSessionFactory() as session:
        user = await get_or_create_ig_user(session, client_id, client_name)
        user_id = user.id
        company_id = user.company_id

        history_rows = (
            await session.execute(
                select(ClientConversation)
                .where(ClientConversation.user_id == user_id)
                .order_by(ClientConversation.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        history = [{"role": r.role, "content": r.message}
                   for r in reversed(history_rows)]

        profile_row = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        # Тот же сборщик, что в Telegram и в Salebot-мосте: тянет из notes
        # имя, пол и уже выданный промокод, иначе бот выдал бы новый.
        client_profile = ai_service.profile_to_context(profile_row)

        session.add(ClientConversation(
            user_id=user_id, property_id=None, role="user", message=user_message,
        ))
        await session.commit()

    async with AsyncSessionFactory() as ai_session:
        raw_reply = await chat_with_client(
            user_message=user_message,
            conversation_history=history,
            client_profile=client_profile,
            company_id=company_id or 0,
            session=ai_session,
            property_id=None,
            channel="instagram",
        )

    # Маркеры [CARD:ID] в Instagram-режиме промпт запрещает, но если модель
    # их всё же вставила — вырезаем, клиент их видеть не должен.
    reply = clean_ai_reply(raw_reply)

    async with AsyncSessionFactory() as session:
        session.add(ClientConversation(
            user_id=user_id, property_id=None, role="assistant", message=reply,
        ))
        await session.commit()

    # Квалификация профиля — в фоне, ответ SMMBOT она не задерживает.
    # Без неё имя/пол/промокод никогда не попадут в client_profiles.notes,
    # и на длинном диалоге бот заново спросит имя и выдаст новый промокод
    # (та же поломка, что чинили в п.3 ТЗ).
    history_for_qualify = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply},
    ]
    asyncio.create_task(_qualify_in_background(user_id, history_for_qualify))

    return reply


# BotManager сохраняем при старте, чтобы уметь писать агентам в Telegram
_bot_manager = None


def _get_notifier_bot(company_id: int | None):
    if _bot_manager is None:
        return None
    bots = getattr(_bot_manager, "_bots", {})
    if company_id and company_id in bots:
        return bots[company_id]
    return next(iter(bots.values()), None)


# ------------------------------------------------------------------ #
#  Регистрация роутов
# ------------------------------------------------------------------ #

def register_instagram_routes(app: web.Application, bot_manager=None) -> None:
    global _bot_manager
    _bot_manager = bot_manager

    # Salebot — асинхронная схема (ACK сразу, ответ отдельным вызовом API)
    app.router.add_post("/webhook/instagram", instagram_webhook)
    app.router.add_post("/webhook/instagram/phone", instagram_phone_webhook)
    app.router.add_post("/webhook/instagram/followup", instagram_followup_webhook)
    # SMMBOT — синхронная схема (ответ возвращается в теле того же запроса)
    app.router.add_post("/webhook/smmbot", smmbot_webhook)
    app.router.add_get("/media/{media_id}", media_proxy)
    app.router.add_get("/health", lambda r: web.json_response(
        {"ok": True, "version": BRIDGE_VERSION,
         "salebot_key": bool(SALEBOT_API_KEY)}))
