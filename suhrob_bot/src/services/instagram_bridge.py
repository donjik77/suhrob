"""
src/services/instagram_bridge.py

Мост между ManyChat (Instagram) и существующей AI-логикой Telegram-бота.

ЧТО ЭТО РЕШАЕТ
--------------
1. Разворачивает маркеры [CARD:162] в реальные карточки (фото + описание),
   ровно как это делает ai_consultation.py в Telegram.
2. Отдаёт фото объектов по публичному HTTPS-URL через прокси /media/<id>,
   потому что Telegram file_id для Instagram бесполезен.
3. Возвращает ответ в формате ManyChat Dynamic Block v2 с content.type = "instagram".

ВАЖНО: content.type ОБЯЗАН быть "instagram", иначе вложения не отрендерятся.
"""

import asyncio
import re
import html as html_lib

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
)
from src.db.repositories.settings_repo import SettingsRepository
from src.utils.formatters import format_property_card
from src.services import ai_service
from src.services.ai_service import chat_with_client

logger = structlog.get_logger()

# ------------------------------------------------------------------ #
#  Настройки
# ------------------------------------------------------------------ #

# Публичный адрес твоего Railway-сервиса. ОБЯЗАТЕЛЬНО задать в переменных
# окружения Railway, иначе Instagram не сможет скачать фото.
# Пример: https://suhrob-production.up.railway.app
PUBLIC_BASE_URL = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")

# АСИНХРОННАЯ СХЕМА: мы больше НЕ отвечаем контентом внутри запроса ManyChat.
# Вебхук мгновенно возвращает пустой ack (укладывается в долю секунды),
# а готовый ответ уходит отдельным вызовом ManyChat API (sendContent).
# Поэтому AI может думать сколько нужно — лимит ManyChat нас не касается.
AI_TIMEOUT_SECONDS = 30

# Токен ManyChat API: Settings -> API -> сгенерировать.
# Добавить в Railway Variables как MANYCHAT_API_TOKEN.
MANYCHAT_API_TOKEN = (getattr(settings, "MANYCHAT_API_TOKEN", "") or "").strip()
MANYCHAT_SEND_URL = "https://api.manychat.com/fb/sending/sendContent"

# Сколько карточек максимум показываем за один ответ.
# Лимит ManyChat — 10 сообщений на ответ. При MAX_PHOTOS_PER_PROPERTY=4
# (4 фото + 1 текст = 5 слотов на объект) больше 2 объектов не влезет —
# 2*5=10 ровно в лимит. Если увеличишь одно число — уменьши другое.
MAX_CARDS_PER_REPLY = 2
MAX_PHOTOS_PER_PROPERTY = 4

# Версия моста — видна в GET /health. По ней проверяем, что Railway
# реально запустил свежий код, а не кэшированную сборку.
BRIDGE_VERSION = "2026-07-25-photos-first-v3"

# Максимальная длина одного текстового сообщения в Instagram DM.
IG_TEXT_LIMIT = 950

# ID компании, к которой относится Instagram-аккаунт.
# Если не задан — берём первую активную компанию.
INSTAGRAM_COMPANY_ID = getattr(settings, "INSTAGRAM_COMPANY_ID", None)


# ------------------------------------------------------------------ #
#  Разбор маркеров [CARD:ID] — та же логика, что в ai_consultation.py
# ------------------------------------------------------------------ #

_CARD_MARKER_RE = re.compile(r"\[CARD\s*:\s*(\d+)\]", re.IGNORECASE)
_VISIBLE_PROPERTY_ID_RE = re.compile(r"(?:CARD_)?(?:#\s*)?ID[_:\-\s]*(\d+)", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Тот же паттерн, что уже используется в Telegram-версии (favorites.py),
# и тот же список триггеров "хочу агента", что в ai_consultation.py.
_PHONE_RE = re.compile(r"^\+?\d[\d\s().\-]{6,}$")
_AGENT_CONNECT_RE = re.compile(
    r"(agent|makler|rieltor|bog'?la|boglan|bog'lan|aloqa|telefon|ko'rish|korish|uchrash)",
    re.IGNORECASE,
)
QUALIFY_SCORE_THRESHOLD = 70


def extract_property_card_ids(reply: str) -> list[int]:
    ids: list[int] = []
    for pattern in (_CARD_MARKER_RE, _VISIBLE_PROPERTY_ID_RE):
        for match in pattern.finditer(reply or ""):
            prop_id = int(match.group(1))
            if prop_id not in ids:
                ids.append(prop_id)
    return ids


def clean_ai_reply(reply: str) -> str:
    """Вырезает строки с маркерами, чтобы клиент не видел [CARD:162]."""
    lines = []
    for line in (reply or "").splitlines():
        if _CARD_MARKER_RE.search(line) or _VISIBLE_PROPERTY_ID_RE.search(line):
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or "Tayyor jigar, mos uylarni yuboryapman."


def strip_html(text: str) -> str:
    """
    Telegram-карточки собраны с HTML-тегами (<b>, <i>).
    Instagram HTML не понимает — показал бы теги как текст.
    """
    text = _HTML_TAG_RE.sub("", text or "")
    return html_lib.unescape(text).strip()


# ------------------------------------------------------------------ #
#  Формат ответа ManyChat Dynamic Block v2
# ------------------------------------------------------------------ #

def mc_response(messages: list[dict], actions: list | None = None,
                quick_replies: list | None = None, keep_listening: bool = True) -> dict:
    response = {
        "version": "v2",
        "content": {
            # Без этой строки вложения в Instagram не работают.
            "type": "instagram",
            "messages": messages[:10],          # лимит ManyChat
            "actions": (actions or [])[:5],
            "quick_replies": (quick_replies or [])[:11],
        },
    }

    if keep_listening and PUBLIC_BASE_URL:
        # КЛЮЧЕВОЙ МОМЕНТ: без этого блока ManyChat отвечает один раз и
        # молчит — следующее сообщение от контакта не попадёт на наш
        # вебхук, пока фло не будет запущено заново с нуля (а для этого
        # нужно, чтобы текст снова совпал с триггером фло, например "uy").
        # external_message_callback говорит ManyChat: "следующее текстовое
        # сообщение этого контакта — сразу сюда, в обход всего фло".
        response["content"]["external_message_callback"] = {
            "url": f"{PUBLIC_BASE_URL}/webhook/instagram",
            "method": "post",
            "headers": {},
            "payload": {
                "user_id": "{{user_id}}",
                "message": "{{last_input_text}}",
            },
            # Максимум, который разрешает ManyChat — 1 день (в секундах).
            # Если контакт не написал за это время, колбэк истекает и
            # следующее сообщение снова пойдёт через обычный триггер фло.
            "timeout": 86400,
        }

    return response


def mc_text(text: str) -> dict:
    return {"type": "text", "text": (text or "")[:IG_TEXT_LIMIT]}


def mc_image(url: str) -> dict:
    return {"type": "image", "url": url}


def mc_ack() -> dict:
    """
    Мгновенный пустой ответ на запрос ManyChat: сообщений нет, но
    external_message_callback внутри mc_response продолжает слушать
    следующие сообщения контакта. Реальный контент уйдёт через API.
    """
    return mc_response([], keep_listening=True)


async def send_via_manychat_api(
    subscriber_id: str,
    messages: list[dict] | None = None,
    groups: list[list[dict]] | None = None,
) -> bool:
    """
    Отправляет готовые сообщения контакту через ManyChat API (sendContent).

    Можно передать либо плоский список messages, либо groups — список
    групп сообщений. Каждая группа уходит ОТДЕЛЬНЫМ вызовом API с паузой
    между вызовами. Это критично для карточек недвижимости: если слать
    описание и фото разных объектов одной пачкой, Instagram доставляет
    тексты мгновенно, а фото с задержкой (Meta ещё скачивает их с нашего
    сервера) — и сообщения перемешиваются: первая карточка выглядит без
    фото, последняя — без описания. Отдельный вызов на каждый объект +
    пауза удерживают порядок: описание объекта, следом его фото.

    Лимит одного вызова — 10 сообщений; группы длиннее 10 дорезаются.
    """
    if not MANYCHAT_API_TOKEN:
        logger.error("manychat_token_missing",
                     hint="Задай MANYCHAT_API_TOKEN в Railway Variables")
        return False

    if groups is None:
        groups = [messages] if messages else []
    groups = [g for g in groups if g]
    if not groups:
        return True

    BATCH = 10
    batches: list[list[dict]] = []
    for group in groups:
        for i in range(0, len(group), BATCH):
            batches.append(group[i:i + BATCH])

    ok_all = True
    for idx, batch in enumerate(batches):
        is_last = idx == len(batches) - 1
        # external_message_callback вешаем только на ПОСЛЕДНЮЮ пачку —
        # подписка на следующее сообщение должна регистрироваться после
        # того, как весь ответ доставлен.
        payload = {
            "subscriber_id": int(subscriber_id),
            "data": mc_response(batch, keep_listening=is_last),
        }

        try:
            async with httpx.AsyncClient(timeout=15) as http:
                resp = await http.post(
                    MANYCHAT_SEND_URL,
                    headers={
                        "Authorization": f"Bearer {MANYCHAT_API_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            body = resp.json() if resp.content else {}
            if not (resp.status_code == 200 and body.get("status") == "success"):
                logger.error("manychat_send_failed", subscriber=subscriber_id,
                             batch=idx, status=resp.status_code, body=str(body)[:300])
                ok_all = False
        except Exception as exc:
            logger.error("manychat_send_error", subscriber=subscriber_id,
                         batch=idx, error=str(exc))
            ok_all = False

        # Пауза между пачками. После пачки С ФОТО ждём дольше: Meta
        # должна успеть скачать и доставить картинки до того, как уйдёт
        # текст следующей карточки — иначе порядок ломается.
        if not is_last:
            has_images = any(
                m.get("type") == "image" for m in batch if isinstance(m, dict)
            )
            await asyncio.sleep(2.5 if has_images else 0.8)

    return ok_all


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


async def get_or_create_ig_user(session, contact_id: str, first_name: str | None) -> User:
    """
    В таблице users ключ — telegram_user_id. Чтобы не делать миграцию,
    Instagram-контакты пишем с ОТРИЦАТЕЛЬНЫМ id: -<manychat_contact_id>.
    Telegram никогда не выдаёт отрицательные user_id, так что коллизий не будет.
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
        username=f"ig_{contact_id}",
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
#  Сборка карточек объектов для Instagram
# ------------------------------------------------------------------ #

async def build_property_messages(session, company_id: int | None,
                                  property_ids: list[int]) -> list[list[dict]]:
    """
    Превращает список ID объектов в ГРУППЫ сообщений ManyChat.
    Одна группа = один объект: [описание, фото, фото, ...].
    Описание идёт ПЕРВЫМ — тексты Instagram доставляет мгновенно,
    а фото с задержкой, поэтому при обратном порядке описание
    "убегало" к чужой карточке. Каждая группа отправляется отдельным
    вызовом API (см. send_via_manychat_api), чтобы карточки
    не перемешивались между собой.
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
        .options(selectinload(Property.media), selectinload(Property.agent))
    )
    props_by_id = {p.id: p for p in result.scalars().all()}
    # Сохраняем порядок, в котором объекты назвал AI
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

    rate = await SettingsRepository(session).get_float("currency_rate_uzs_per_usd", 12600.0)

    groups: list[list[dict]] = []
    for prop in props:
        # Фото объекта (видео пропускаем — Instagram-канал его не
        # поддерживает), берём первые MAX_PHOTOS_PER_PROPERTY штук.
        photos = [
            m for m in (prop.media or [])
            if getattr(m.file_type, "value", m.file_type) == FileType.photo.value
        ][:MAX_PHOTOS_PER_PROPERTY]

        # 1. ФОТО — отдельной группой, уходят отдельным вызовом API
        if photos and PUBLIC_BASE_URL:
            groups.append([
                # .jpg в конце обязателен: Instagram/ManyChat может не
                # принять URL картинки без расширения файла
                mc_image(f"{PUBLIC_BASE_URL}/media/{photo.id}.jpg")
                for photo in photos
            ])
        else:
            # Явно логируем причину отсутствия фото — либо у объекта в базе
            # нет ни одной фотографии (только видео/ничего), либо не задан
            # PUBLIC_BASE_URL. Без этого лога непонятно, баг это или данные.
            logger.warning(
                "ig_no_photo_for_property",
                property_id=prop.id,
                media_count=len(prop.media or []),
                has_public_base_url=bool(PUBLIC_BASE_URL),
            )

        # 2. ОПИСАНИЕ — следующей отдельной группой. Между группами стоит
        # пауза (после группы с фото — увеличенная), поэтому описание
        # приходит ПОСЛЕ фото своего объекта и не убегает к соседней
        # карточке. Порядок как в Telegram: фото → текст.
        caption = strip_html(format_property_card(prop, rate))
        groups.append([mc_text(caption)])

    # ПРЕДПРОГРЕВ: скачиваем все фото из Telegram в кэш ДО отправки.
    # Instagram заберёт их с нашего сервера мгновенно — фото не будут
    # опаздывать и порядок "описание → фото" сохранится.
    photo_ids: list[int] = []
    for prop in props:
        for m in (prop.media or []):
            if getattr(m.file_type, "value", m.file_type) == FileType.photo.value:
                photo_ids.append(m.id)
    await prefetch_media(photo_ids[:MAX_CARDS_PER_REPLY * MAX_PHOTOS_PER_PROPERTY])

    return groups


# ------------------------------------------------------------------ #
#  Прокси для фото: Telegram file_id -> публичный HTTPS-URL
# ------------------------------------------------------------------ #

_file_path_cache: dict[int, str] = {}

# Кэш САМИХ БАЙТОВ фото. Критично для порядка сообщений: Instagram
# доставляет фото клиенту только после того, как скачает его с нашего
# сервера. Если при этом мы ходим в Telegram (1-3 сек на фото) — фото
# опаздывают, и тексты следующих карточек проскакивают вперёд.
# Поэтому перед отправкой карточек мы ПРЕДПРОГРЕВАЕМ кэш (скачиваем
# все фото заранее), и Meta получает байты мгновенно.
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
    """Параллельно прогревает кэш фото ДО отправки карточек клиенту."""
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
    Отдаёт байты фото наружу (для Instagram). Сначала смотрит кэш —
    после предпрогрева ответ мгновенный, скачивание из Telegram
    происходит только если кэш пуст.
    """
    try:
        raw_id = request.match_info["media_id"]
        # Принимаем и "455", и "455.jpg" — расширение просто отбрасываем
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
        )


async def instagram_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/instagram

    Тело запроса из ManyChat (вкладка Body) — ТОЛЬКО для самого первого
    сообщения, которое ManyChat присылает через ручной Dynamic block во фло:
    {
      "user_id": "{{Contact Id}}",
      "message": "{{Last Text Input}}",
      "first_name": "{{First Name}}",
      "gender": "{{Gender}}"
    }

    Все СЛЕДУЮЩИЕ сообщения этого контакта прилетают сюда же, но уже через
    external_message_callback (см. mc_response) — в его payload доступны
    только user_id и message, gender там не передаётся. Это не баг: пол
    там просто не пробрасывается ManyChat-ом. AI получает его один раз в
    начале разговора и обычно этого достаточно, чтобы удержать обращение.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response(mc_response([mc_text("Xatolik yuz berdi.")]))

    contact_id = str(data.get("user_id") or "").strip()
    user_message = (data.get("message") or "").strip()
    first_name = data.get("first_name")
    gender = (data.get("gender") or "").lower()

    if not contact_id or not user_message:
        return web.json_response(mc_response([
            mc_text("Salom jigar! Qanaqa uy kerak, yozing 🏡")
        ]))

    logger.info("ig_message_in", contact=contact_id, text=user_message[:100])

    # АСИНХРОННАЯ СХЕМА: немедленно подтверждаем приём (ManyChat получает
    # валидный пустой ответ за доли секунды — таймаут 499 невозможен),
    # а думаем и отвечаем в фоне через ManyChat API.
    asyncio.create_task(
        _process_and_reply(contact_id, user_message, first_name, gender)
    )
    return web.json_response(mc_ack())


async def _process_and_reply(contact_id: str, user_message: str,
                             first_name: str | None, gender: str) -> None:
    """
    Вся тяжёлая работа — вне HTTP-запроса ManyChat:
    пользователь -> история -> AI -> карточки -> отправка через API.
    """
    # 1. Пользователь + история + профиль
    async with AsyncSessionFactory() as session:
        user = await get_or_create_ig_user(session, contact_id, first_name)
        company_id = user.company_id

        # Телефон, присланный текстом — отдельная быстрая ветка без AI
        if not user.phone and _PHONE_RE.match(user_message):
            reply = await _handle_phone_submission(session, user, user_message)
            await send_via_manychat_api(
                contact_id, reply.get("content", {}).get("messages", [])
            )
            return

        history_rows = (
            await session.execute(
                select(ClientConversation)
                .where(ClientConversation.user_id == user.id)
                .order_by(ClientConversation.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        history = [{"role": r.role, "content": r.message} for r in reversed(history_rows)]

        session.add(ClientConversation(
            user_id=user.id, property_id=None, role="user", message=user_message,
        ))
        await session.commit()

        profile_row = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == user.id)
            )
        ).scalar_one_or_none()

        client_profile = {}
        if profile_row:
            client_profile = {
                "budget_min_usd": profile_row.budget_min_usd,
                "budget_max_usd": profile_row.budget_max_usd,
                "preferred_districts": profile_row.preferred_districts or [],
                "preferred_rooms": profile_row.preferred_rooms,
                "purchase_timeline": profile_row.purchase_timeline,
                "payment_method": profile_row.payment_method,
                "qualification_score": profile_row.qualification_score,
            }

    # 2. Подсказка про пол, чтобы бот не сказал девушке "jigar"
    prompt_text = user_message
    if gender == "female":
        prompt_text += "\n[Mijoz ayol — 'singlim/opa' deb murojaat qil]"
    elif gender == "male":
        prompt_text += "\n[Mijoz erkak — 'jigar/radnoy/aka' deb murojaat qil]"

    # 3. Вызов AI — теперь можно ждать по-настоящему (мы вне HTTP-запроса)
    try:
        raw_reply = await asyncio.wait_for(
            _run_ai(prompt_text, history, client_profile, company_id),
            timeout=AI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("ig_ai_timeout", contact=contact_id)
        await send_via_manychat_api(contact_id, [
            mc_text("Sal sekinlashdim jigar, yana bir marta yozib yuboring 🤝")
        ])
        return
    except Exception as exc:
        logger.error("ig_ai_error", contact=contact_id, error=str(exc))
        await send_via_manychat_api(contact_id, [
            mc_text("Kechirasiz, texnik nosozlik. Qaytadan urinib ko'ring.")
        ])
        return

    # 4. Разворачиваем [CARD:162] в реальные карточки.
    # Ответ собираем ГРУППАМИ: [текст AI], [карточка 1], [карточка 2], ...
    # Каждая группа уйдёт отдельным вызовом ManyChat API — так описание
    # и фото одного объекта не перемешиваются с соседним.
    card_ids = extract_property_card_ids(raw_reply)
    text_reply = clean_ai_reply(raw_reply) if card_ids else raw_reply

    groups: list[list[dict]] = [[mc_text(text_reply)]]

    async with AsyncSessionFactory() as session:
        if card_ids:
            groups.extend(await build_property_messages(session, company_id, card_ids))

        session.add(ClientConversation(
            user_id=user.id, property_id=None, role="assistant", message=text_reply,
        ))
        await session.commit()

        # 5. Быстрый детект "клиент попросил агента" — по ключевым словам.
        # Квалификация — отдельной фоновой задачей, как и раньше.
        should_ask_phone = (
            not user.phone and bool(_AGENT_CONNECT_RE.search(user_message))
        )

        history_for_qualify = history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": text_reply},
        ]
        asyncio.create_task(_qualify_in_background(user.id, history_for_qualify))

    if should_ask_phone:
        groups.append([mc_text(
            "Agent bilan bog'lab qo'yishim uchun telefon raqamingizni "
            "yozib yuboring (masalan: +998901234567) 📞"
        )])

    sent = await send_via_manychat_api(contact_id, groups=groups)
    logger.info("ig_message_out", contact=contact_id, cards=len(card_ids),
                asked_phone=should_ask_phone, sent=sent)


async def _qualify_in_background(user_id: int, history: list[dict]) -> None:
    """
    Запускается через asyncio.create_task после ответа клиенту.
    Клиент уже получил сообщение, здесь просто обновляем профиль в БД —
    результат нужен только для будущих сообщений и уведомлений агенту.
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


async def _handle_phone_submission(session, user: User, phone_text: str) -> dict:
    """
    Клиент прислал номер телефона отдельным сообщением (без нажатия
    какой-либо кнопки в ManyChat — просто написал текстом). Сохраняем,
    квалифицируем по уже накопленному профилю и уведомляем агента —
    той же функцией, что использует Telegram-версия.
    """
    from src.bot.handlers.client.ai_consultation import _maybe_assign_hot_lead

    phone = phone_text if phone_text.startswith("+") else f"+{phone_text}"
    user.phone = phone
    await session.commit()

    profile = (
        await session.execute(
            select(ClientProfile).where(ClientProfile.user_id == user.id)
        )
    ).scalar_one_or_none()

    qualification = {
        "qualification_score": (profile.qualification_score if profile else 0),
        "budget_min_usd": (profile.budget_min_usd if profile else None),
        "budget_max_usd": (profile.budget_max_usd if profile else None),
        "preferred_districts": (profile.preferred_districts if profile else []),
        "preferred_rooms": (profile.preferred_rooms if profile else []),
        "purchase_timeline": (profile.purchase_timeline if profile else None),
        "payment_method": (profile.payment_method if profile else None),
        "summary": ((profile.notes if profile else None) or "Instagram orqali murojaat"),
    }

    bot = _get_notifier_bot(user.company_id)
    if bot is not None:
        try:
            await _maybe_assign_hot_lead(
                session, user, qualification, bot,
                client_phone=phone, property_id=None,
            )
        except Exception as exc:
            logger.warning("ig_lead_notify_failed", error=str(exc))
    else:
        logger.warning("ig_lead_notify_skipped_no_bot", user_id=user.id)

    return mc_response([
        mc_text("Rahmat jigar! Agentimiz tez orada bog'lanadi 🤝")
    ])


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
        if data.get("summary"):
            existing.notes = data["summary"]
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
            notes=data.get("summary"),
            last_contact_at=now,
        ))
    await session.commit()


# ------------------------------------------------------------------ #
#  Приём телефона (отдельный шаг воронки в ManyChat)
# ------------------------------------------------------------------ #

async def instagram_phone_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/instagram/phone
    Тело: {"user_id": "{{Contact Id}}", "phone": "{{Phone}}"}

    Вызывать из ManyChat после того, как клиент оставил номер.
    Сохраняет телефон и уведомляет агента в Telegram.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response(mc_response([mc_text("Xatolik.")]))

    contact_id = str(data.get("user_id") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not contact_id or not phone:
        return web.json_response(mc_response([
            mc_text("Telefon raqamingizni +998901234567 ko'rinishida yuboring.")
        ]))

    from src.bot.handlers.client.ai_consultation import _maybe_assign_hot_lead

    async with AsyncSessionFactory() as session:
        user = await get_or_create_ig_user(session, contact_id, None)
        user.phone = phone
        await session.commit()

        profile = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == user.id)
            )
        ).scalar_one_or_none()

        qualification = {
            "qualification_score": (profile.qualification_score if profile else 0),
            "budget_min_usd": (profile.budget_min_usd if profile else None),
            "budget_max_usd": (profile.budget_max_usd if profile else None),
            "preferred_districts": (profile.preferred_districts if profile else []),
            "preferred_rooms": (profile.preferred_rooms if profile else []),
            "purchase_timeline": (profile.purchase_timeline if profile else None),
            "payment_method": (profile.payment_method if profile else None),
            "summary": ((profile.notes if profile else None) or "Instagram orqali murojaat"),
        }

        bot = _get_notifier_bot(user.company_id)
        if bot is not None:
            try:
                await _maybe_assign_hot_lead(
                    session, user, qualification, bot,
                    client_phone=phone, property_id=None,
                )
            except Exception as exc:
                logger.warning("ig_lead_notify_failed", error=str(exc))

    return web.json_response(mc_response([
        mc_text("Rahmat! Agentimiz tez orada bog'lanadi 🤝")
    ]))


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

    app.router.add_post("/webhook/instagram", instagram_webhook)
    app.router.add_post("/webhook/instagram/phone", instagram_phone_webhook)
    app.router.add_get("/media/{media_id}", media_proxy)
    app.router.add_get("/health", lambda r: web.json_response(
        {"ok": True, "version": BRIDGE_VERSION}))
