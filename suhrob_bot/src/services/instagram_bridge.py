"""
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

PUBLIC_BASE_URL = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
AI_TIMEOUT_SECONDS = 12
MAX_CARDS_PER_REPLY = 3
IG_TEXT_LIMIT = 950
INSTAGRAM_COMPANY_ID = getattr(settings, "INSTAGRAM_COMPANY_ID", None)


# ------------------------------------------------------------------ #
#  Разбор маркеров [CARD:ID]
# ------------------------------------------------------------------ #

_CARD_MARKER_RE = re.compile(r"\[CARD\s*:\s*(\d+)\]", re.IGNORECASE)
_VISIBLE_PROPERTY_ID_RE = re.compile(r"(?:CARD_)?(?:#\s*)?ID[_:\-\s]*(\d+)", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


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
                quick_replies: list | None = None) -> dict:
    return {
        "version": "v2",
        "content": {
            "type": "instagram",
            "messages": messages[:10],
            "actions": (actions or [])[:5],
            "quick_replies": (quick_replies or [])[:11],
        },
    }


def mc_text(text: str) -> dict:
    return {"type": "text", "text": (text or "")[:IG_TEXT_LIMIT]}


def mc_image(url: str) -> dict:
    return {"type": "image", "url": url}


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
                                  property_ids: list[int]) -> list[dict]:
    """Превращает список ID объектов в сообщения ManyChat (фото + описание)."""
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

    messages: list[dict] = []
    for prop in props:
        photo = next(
            (m for m in (prop.media or [])
             if getattr(m.file_type, "value", m.file_type) == FileType.photo.value),
            None,
        )
        if photo and PUBLIC_BASE_URL:
            messages.append(mc_image(f"{PUBLIC_BASE_URL}/media/{photo.id}"))

        caption = strip_html(format_property_card(prop, rate))
        messages.append(mc_text(caption))

    return messages


# ------------------------------------------------------------------ #
#  Прокси для фото: Telegram file_id -> публичный HTTPS-URL
# ------------------------------------------------------------------ #

_file_path_cache: dict[int, str] = {}


async def media_proxy(request: web.Request) -> web.Response:
    """
    GET /media/<media_id>
    Скачивает файл из Telegram по file_id и отдаёт байты наружу.
    """
    try:
        media_id = int(request.match_info["media_id"])
    except (KeyError, ValueError):
        return web.Response(status=400, text="bad media id")

    async with AsyncSessionFactory() as session:
        media = (
            await session.execute(
                select(PropertyMedia)
                .where(PropertyMedia.id == media_id)
                .options(selectinload(PropertyMedia.property))
            )
        ).scalar_one_or_none()

        if not media:
            return web.Response(status=404, text="not found")

        company = (
            await session.execute(
                select(Company).where(Company.id == media.property.company_id)
            )
        ).scalar_one_or_none()

    if not company or not company.bot_token:
        return web.Response(status=404, text="no bot token")

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
                    return web.Response(status=502, text="telegram getFile failed")
                file_path = data["result"]["file_path"]
                _file_path_cache[media_id] = file_path

            file_resp = await http.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}"
            )
            if file_resp.status_code != 200:
                _file_path_cache.pop(media_id, None)
                return web.Response(status=502, text="telegram download failed")

            content_type = "image/jpeg"
            if file_path.lower().endswith(".png"):
                content_type = "image/png"

            return web.Response(
                body=file_resp.content,
                content_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except Exception as exc:
        logger.error("media_proxy_error", media_id=media_id, error=str(exc))
        return web.Response(status=500, text="proxy error")


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

    Тело запроса из ManyChat:
    {
      "user_id": "{{Contact Id}}",
      "message": "{{Last Text Input}}",
      "first_name": "{{First Name}}",
      "gender": "{{Gender}}"
    }
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

    async with AsyncSessionFactory() as session:
        user = await get_or_create_ig_user(session, contact_id, first_name)
        company_id = user.company_id

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

    prompt_text = user_message
    if gender == "female":
        prompt_text += "\n[Mijoz ayol — 'singlim/opa' deb murojaat qil]"
    elif gender == "male":
        prompt_text += "\n[Mijoz erkak — 'jigar/radnoy/aka' deb murojaat qil]"

    try:
        raw_reply = await asyncio.wait_for(
            _run_ai(prompt_text, history, client_profile, company_id),
            timeout=AI_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("ig_ai_timeout", contact=contact_id)
        return web.json_response(mc_response([
            mc_text("Sal sekinlashdim jigar, yana bir marta yozib yuboring 🤝")
        ]))
    except Exception as exc:
        logger.error("ig_ai_error", contact=contact_id, error=str(exc))
        return web.json_response(mc_response([
            mc_text("Kechirasiz, texnik nosozlik. Qaytadan urinib ko'ring.")
        ]))

    card_ids = extract_property_card_ids(raw_reply)
    text_reply = clean_ai_reply(raw_reply) if card_ids else raw_reply

    messages: list[dict] = [mc_text(text_reply)]

    async with AsyncSessionFactory() as session:
        if card_ids:
            messages.extend(await build_property_messages(session, company_id, card_ids))

        session.add(ClientConversation(
            user_id=user.id, property_id=None, role="assistant", message=text_reply,
        ))
        await session.commit()

        try:
            all_history = history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": text_reply},
            ]
            qualification = await ai_service.qualify_client(all_history)
            await _upsert_profile(session, user.id, qualification)
        except Exception as exc:
            logger.warning("ig_qualify_failed", error=str(exc))

    logger.info("ig_message_out", contact=contact_id, cards=len(card_ids))
    return web.json_response(mc_response(messages))


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
#  Приём телефона
# ------------------------------------------------------------------ #

async def instagram_phone_webhook(request: web.Request) -> web.Response:
    """
    POST /webhook/instagram/phone
    Тело: {"user_id": "{{Contact Id}}", "phone": "{{Phone}}"}
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
    app.router.add_get("/health", lambda r: web.json_response({"ok": True}))
