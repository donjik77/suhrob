"""
AI consultation handler — free dialog with Claude for clients.
Triggered by main menu button or property card inline button.
"""
import asyncio
import re

import structlog

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    User, UserRole, Company, ClientProfile, ClientConversation, Property,
    PropertyStatus, LeadAssignment, LeadStatus,
)
from src.db.session import AsyncSessionFactory
from src.bot.handlers.client.property_access import get_active_property_for_client, resolve_client_company_id
from src.bot.keyboards.client import property_card_kb, request_client_phone_kb
from src.bot.handlers.client.favorites import _extract_phone
from src.bot.utils.property_media import answer_property_media_card
from src.config import settings
from src.db.repositories.settings_repo import SettingsRepository
from src.services import ai_service
from src.utils.formatters import format_property_card
from locales.uz import t

router = Router()

AI_DAILY_LIMIT = settings.AI_DAILY_LIMIT_PER_USER


async def check_ai_limit(user_id: int, redis, daily_limit: int = AI_DAILY_LIMIT) -> tuple[bool, int]:
    from datetime import datetime, timezone
    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"ai_calls:{user_id}:{today_key}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 86400)
    return count <= daily_limit, count


class ConsultState(StatesGroup):
    chatting = State()
    waiting_phone_for_agent = State()


_CARD_MARKER_RE = re.compile(r"\[CARD\s*:\s*(\d+)\]", re.IGNORECASE)
_VISIBLE_PROPERTY_ID_RE = re.compile(r"(?:CARD_)?(?:#\s*)?ID[_:\-\s]*(\d+)", re.IGNORECASE)
# Триггеры "хочу агента". Прежний список ловил несколько книжных слов, а
# клиенты пишут иначе: "qo'ng'iroq qiling", "raqamingiz bormi", "gaplashsam
# bo'ladimi", "kelib ko'rsam", по-русски "позвоните", "риелтор". Держим
# синхронно с _AGENT_CONNECT_RE в instagram_bridge.py — оба канала должны
# реагировать на одни и те же формулировки.
_AGENT_CONNECT_RE = re.compile(
    r"(agent|makler|rieltor|rialtor|broker|menejer|mutaxassis"
    r"|bog'?la|boglan|bog'lan|aloqa|kontakt|murojaat"
    r"|telefon|raqam|nomer|qo'?ng'?iroq|qongiroq|zvonok"
    r"|gaplash|suhbatlash|uchrash|ko'?rish|korish|kelsam|kelib"
    r"|агент|риелтор|риэлтор|маклер|менеджер|позвон|звонит|связ|контакт"
    r"|телефон|номер|встрет|посмотрет)",
    re.IGNORECASE,
)


def _extract_property_card_ids(reply: str) -> list[int]:
    ids: list[int] = []
    for pattern in (_CARD_MARKER_RE, _VISIBLE_PROPERTY_ID_RE):
        for match in pattern.finditer(reply or ""):
            prop_id = int(match.group(1))
            if prop_id not in ids:
                ids.append(prop_id)
    return ids


def _clean_ai_reply_for_cards(reply: str) -> str:
    lines = []
    for line in (reply or "").splitlines():
        if _CARD_MARKER_RE.search(line) or _VISIBLE_PROPERTY_ID_RE.search(line):
            continue
        lines.append(line)

    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text or "Tayyor jigar, mos uylarni kartochka qilib yuboryapman."


def _wants_agent_connection(text: str | None) -> bool:
    return bool(_AGENT_CONNECT_RE.search(text or ""))


async def _send_ai_property_cards(message: Message, company_id: int | None, property_ids: list[int]) -> None:
    if not company_id or not property_ids:
        return

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Property)
            .where(
                Property.company_id == company_id,
                Property.status == PropertyStatus.active,
                Property.id.in_(property_ids),
            )
            .options(selectinload(Property.media), selectinload(Property.agent))
        )
        props_by_id = {prop.id: prop for prop in result.scalars().all()}
        props = [props_by_id[prop_id] for prop_id in property_ids if prop_id in props_by_id]

        if not props:
            return

        await session.execute(
            update(Property)
            .where(Property.company_id == company_id, Property.id.in_([prop.id for prop in props]))
            .values(views_count=Property.views_count + 1)
        )
        await session.commit()

        settings_repo = SettingsRepository(session)
        rate = await settings_repo.get_float("currency_rate_uzs_per_usd", 12600.0)

        for prop in props:
            await answer_property_media_card(
                message,
                media_items=prop.media,
                caption=format_property_card(prop, rate),
                reply_markup=property_card_kb(prop.id),
                parse_mode="HTML",
                caption_entities_json=prop.custom_text_entities_json if prop.custom_text else None,
            )


# ------------------------------------------------------------------ #
#  Entry points
# ------------------------------------------------------------------ #

@router.message(F.text.contains("Konsultatsiya"))
async def start_consultation(message: Message, db_user: User, state: FSMContext):
    await state.set_state(ConsultState.chatting)
    await state.update_data(property_id=None)
    await message.answer(
        "🤖 <b>AI-konsultant</b>\n\n"
        "Salom! Sizga qanday ko'chmas mulk kerakligi haqida gapirib bering.\n"
        "Men sizga mos variantlarni topishda yordam beraman.\n\n"
        "❌ Chiqish uchun /stop yozing.",
        reply_markup=None,
    )


@router.callback_query(F.data.startswith("ai_consult:"))
async def start_consultation_property(callback: CallbackQuery, db_user: User, company: Company | None, state: FSMContext):
    property_id = int(callback.data.split(":")[1])
    company_id = resolve_client_company_id(company, db_user)

    async with AsyncSessionFactory() as session:
        prop = await get_active_property_for_client(property_id, company_id, session)
    if not prop:
        await callback.answer("❌ Bunday obyekt mavjud emas yoki sotilgan", show_alert=True)
        return

    await state.set_state(ConsultState.chatting)
    await state.update_data(property_id=property_id)
    await callback.message.answer(
        "🤖 <b>AI-konsultant</b>\n\nBu obyekt haqida savolingiz bormi?\n"
        "❌ Chiqish: /stop"
    )
    await callback.answer()


# ------------------------------------------------------------------ #
#  Message handler inside consultation
# ------------------------------------------------------------------ #

@router.message(ConsultState.waiting_phone_for_agent)
async def receive_ai_agent_phone(message: Message, db_user: User, state: FSMContext):
    phone = _extract_phone(message)
    if not phone:
        await message.answer(
            "Telefon raqam noto'g'ri. Kontakt tugmasi orqali yuboring yoki +998901234567 formatida yozing.",
            reply_markup=request_client_phone_kb(),
        )
        return

    data = await state.get_data()
    property_id = data.get("property_id")

    async with AsyncSessionFactory() as session:
        await session.execute(
            update(User)
            .where(User.id == db_user.id)
            .values(phone=phone)
        )
        await session.commit()
        db_user.phone = phone

    # Уведомление агенту собирается из накопленного профиля. Раньше сюда
    # прокидывалась qualification из FSM — она пропадала при рестарте бота
    # или при выходе из состояния, и агент получал лид с пустыми полями.
    await _notify_agent_background(db_user.id, message.bot, property_id)

    await state.set_state(ConsultState.chatting)
    await state.update_data(property_id=property_id)
    await message.answer(
        "Rahmat! Telefon raqamingiz agentga yuborildi.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(ConsultState.chatting)
async def handle_consultation_message(message: Message, db_user: User, state: FSMContext):
    if message.text and message.text.startswith("/stop"):
        await state.clear()
        await message.answer("Konsultatsiya yakunlandi. Asosiy menyuga qaytdingiz.")
        return

    fsm_data = await state.get_data()
    property_id: int | None = fsm_data.get("property_id")

    import redis.asyncio as aioredis
    _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        allowed, count = await check_ai_limit(db_user.id, _redis)
    finally:
        await _redis.aclose()

    if not allowed:
        await message.answer(
            f"🚫 <b>Kunlik limit tugadi</b>\n\n"
            f"Siz bugun {count} ta xabar yubordingiz. "
            f"Ertaga yana yozing yoki agent bilan bog'laning.",
            parse_mode='HTML',
        )
        return

    async with AsyncSessionFactory() as session:
        # Load conversation history (last 10 messages)
        history_rows = (
            await session.execute(
                select(ClientConversation)
                .where(ClientConversation.user_id == db_user.id)
                .order_by(ClientConversation.created_at.desc())
                .limit(10)
            )
        ).scalars().all()
        history = [{"role": r.role, "content": r.message} for r in reversed(history_rows)]
        history.append({"role": "user", "content": message.text or ""})

        # Save user message
        session.add(ClientConversation(
            user_id=db_user.id,
            property_id=property_id,
            role="user",
            message=message.text or "",
        ))
        await session.commit()

        # Build client profile for AI context
        profile_row = (
            await session.execute(
                select(ClientProfile).where(ClientProfile.user_id == db_user.id)
            )
        ).scalar_one_or_none()
        # Один сборщик на оба канала — включает имя/пол/промокод из notes,
        # без них format_client_profile заново просил имя и генерировал
        # новый промокод на каждом длинном диалоге.
        client_profile = ai_service.profile_to_context(profile_row)

    await message.bot.send_chat_action(message.chat.id, "typing")

    from src.services.ai_service import chat_with_client
    async with AsyncSessionFactory() as ai_session:
        raw_reply = await chat_with_client(
            user_message=message.text or "",
            conversation_history=history[:-1],
            client_profile=client_profile,
            company_id=db_user.company_id or 0,
            session=ai_session,
            property_id=property_id,
        )
    property_card_ids = _extract_property_card_ids(raw_reply)
    reply = _clean_ai_reply_for_cards(raw_reply) if property_card_ids else raw_reply

    wants_agent = _wants_agent_connection(message.text)

    # Save assistant reply
    async with AsyncSessionFactory() as session:
        session.add(ClientConversation(
            user_id=db_user.id,
            property_id=property_id,
            role="assistant",
            message=reply,
        ))
        await session.commit()

    # Клиент явно попросил агента — решаем СРАЗУ по ключевым словам.
    # Это не требует AI и не задерживает ответ.
    needs_phone_for_agent = wants_agent and not db_user.phone

    # ОТВЕЧАЕМ. Всё, что ниже, клиента больше не задерживает.
    #
    # Раньше здесь стоял await ai_service.qualify_client(...) — ВТОРОЙ вызов
    # LLM подряд, и клиент ждал оба. В Instagram-пути квалификация уже давно
    # уходила в фон, Telegram остался на синхронной схеме — отсюда и было
    # "бот стал долго отвечать".
    await message.answer(reply)
    await _send_ai_property_cards(message, db_user.company_id, property_card_ids)

    if wants_agent and db_user.phone:
        # Телефон уже есть — уведомляем агента, тоже в фоне.
        asyncio.create_task(
            _notify_agent_background(db_user.id, message.bot, property_id)
        )

    if needs_phone_for_agent:
        await state.set_state(ConsultState.waiting_phone_for_agent)
        await state.update_data(property_id=property_id)
        await message.answer(
            "Agent bilan bog'lash uchun telefon raqamingizni yuboring.",
            reply_markup=request_client_phone_kb(),
        )

    # Квалификация профиля + горячий лид по score — в фоне.
    all_history = history + [{"role": "assistant", "content": reply}]
    asyncio.create_task(
        _qualify_in_background(db_user.id, all_history, message.bot, property_id)
    )


# ------------------------------------------------------------------ #
#  Фоновые задачи (клиент их не ждёт)
# ------------------------------------------------------------------ #

logger = structlog.get_logger()

QUALIFY_SCORE_THRESHOLD = 70


async def _qualify_in_background(user_id: int, history: list[dict], bot,
                                 property_id: int | None) -> None:
    """
    Квалификация профиля после того, как клиент уже получил ответ.

    Тот же паттерн, что в instagram_bridge._qualify_in_background: результат
    нужен только для будущих сообщений и для уведомления агента, поэтому
    держать на нём ответ клиенту незачем.
    """
    try:
        qualification = await asyncio.wait_for(
            ai_service.qualify_client(history), timeout=25
        )
    except asyncio.TimeoutError:
        logger.warning("qualify_bg_timeout", user_id=user_id)
        return
    except Exception as exc:
        logger.warning("qualify_bg_failed", user_id=user_id, error=str(exc))
        return

    try:
        async with AsyncSessionFactory() as session:
            await _upsert_client_profile(session, user_id, qualification)

            # Горячий лид по score. wants_agent обрабатывается синхронно в
            # хендлере, здесь остаётся только порог квалификации.
            if qualification.get("qualification_score", 0) < QUALIFY_SCORE_THRESHOLD:
                return
            client = await session.get(User, user_id)
            if not client or not client.phone:
                return
            await _maybe_assign_hot_lead(
                session, client, qualification, bot,
                client_phone=client.phone, property_id=property_id,
            )
    except Exception as exc:
        logger.warning("qualify_bg_save_failed", user_id=user_id, error=str(exc))


async def _notify_agent_background(user_id: int, bot,
                                   property_id: int | None) -> None:
    """Клиент попросил агента и телефон уже есть — уведомляем в фоне."""
    try:
        async with AsyncSessionFactory() as session:
            client = await session.get(User, user_id)
            if not client or not client.phone:
                return
            profile = (
                await session.execute(
                    select(ClientProfile).where(ClientProfile.user_id == user_id)
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
                # notes — JSON, поэтому резюме достаём распаковщиком, иначе
                # агенту прилетел бы сырой JSON.
                "summary": ai_service.profile_summary(
                    profile.notes if profile else None
                ) or "Mijoz agent bilan bog'lanishni so'radi",
            }
            await _maybe_assign_hot_lead(
                session, client, qualification, bot,
                client_phone=client.phone, property_id=property_id,
            )
            logger.info("agent_notified_bg", user_id=user_id)
    except Exception as exc:
        logger.warning("agent_notify_bg_failed", user_id=user_id, error=str(exc))


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

async def _build_properties_summary(session: AsyncSession, company_id: int | None) -> str:
    if not company_id:
        return "Mavjud obyektlar yo'q."
    from src.db.models import PropertyStatus
    rows = (
        await session.execute(
            select(Property)
            .where(Property.company_id == company_id, Property.status == PropertyStatus.active)
            .limit(20)
        )
    ).scalars().all()
    if not rows:
        return "Hozircha faol obyektlar yo'q."
    lines = []
    for p in rows:
        lines.append(
            f"- {p.property_type.value}, {p.location_district}, {p.rooms} xona, "
            f"${p.price_usd}, ID:{p.id}"
        )
    return "\n".join(lines)


async def _upsert_client_profile(session: AsyncSession, user_id: int, data: dict) -> None:
    from datetime import datetime, timezone
    existing = (
        await session.execute(
            select(ClientProfile).where(ClientProfile.user_id == user_id)
        )
    ).scalar_one_or_none()

    score = data.get("qualification_score", 0)
    now = datetime.now(timezone.utc)

    if existing:
        if data.get("budget_min_usd") is not None:
            existing.budget_min_usd = data["budget_min_usd"]
        if data.get("budget_max_usd") is not None:
            existing.budget_max_usd = data["budget_max_usd"]
        if data.get("preferred_districts"):
            existing.preferred_districts = data["preferred_districts"]
        if data.get("preferred_rooms"):
            existing.preferred_rooms = data["preferred_rooms"]
        if data.get("property_type"):
            existing.property_type = data["property_type"]
        if data.get("purchase_timeline"):
            existing.purchase_timeline = data["purchase_timeline"]
        if data.get("payment_method"):
            existing.payment_method = data["payment_method"]
        existing.qualification_score = max(existing.qualification_score, score)
        # Имя, пол и промокод не имеют колонок — живут в notes как JSON.
        # merge_profile_notes не даёт новому вызову затереть уже выданный
        # промокод, если модель на этом шаге его не увидела.
        existing.notes = ai_service.merge_profile_notes(existing.notes, data)
        existing.last_contact_at = now
    else:
        profile = ClientProfile(
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
        )
        session.add(profile)
    await session.commit()


async def _maybe_assign_hot_lead_legacy(session: AsyncSession, client: User, qualification: dict, bot) -> None:
    from sqlalchemy import select as _select
    existing = (
        await session.execute(
            _select(LeadAssignment).where(
                LeadAssignment.client_user_id == client.id,
                LeadAssignment.status == LeadStatus.new,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return

    from src.db.models import UserRole as UR
    agent = (
        await session.execute(
            _select(User).where(
                User.company_id == client.company_id,
                User.role == UR.agent,
                User.is_blocked == False,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if not agent:
        return

    assignment = LeadAssignment(
        client_user_id=client.id,
        agent_user_id=agent.id,
        status=LeadStatus.new,
        notes=qualification.get("summary", ""),
    )
    session.add(assignment)
    await session.commit()

    score = qualification.get("qualification_score", 0)
    budget_min = qualification.get("budget_min_usd")
    budget_max = qualification.get("budget_max_usd")
    budget = f"${budget_min}-${budget_max}" if budget_min and budget_max else "—"
    districts = ", ".join(qualification.get("preferred_districts") or []) or "—"
    rooms = ", ".join(str(r) for r in (qualification.get("preferred_rooms") or [])) or "—"

    from locales.uz import t
    msg = t(
        "hot_lead_notify",
        client_name=client.full_name or client.username or "Anonim",
        score=score,
        budget=budget,
        districts=districts,
        rooms=rooms,
        timeline=qualification.get("purchase_timeline") or "—",
        payment_method=qualification.get("payment_method") or "—",
        summary=qualification.get("summary") or "—",
    )

    try:
        await bot.send_message(agent.telegram_user_id, msg, parse_mode="HTML")
    except Exception:
        import structlog
        structlog.get_logger().warning("hot_lead_notify_failed", agent_id=agent.id)


async def _maybe_assign_hot_lead(
    session: AsyncSession,
    client: User,
    qualification: dict,
    bot,
    *,
    client_phone: str | None = None,
    property_id: int | None = None,
) -> None:
    from sqlalchemy import select as _select
    from src.db.models import UserRole as UR

    existing = (
        await session.execute(
            _select(LeadAssignment).where(
                LeadAssignment.client_user_id == client.id,
                LeadAssignment.status == LeadStatus.new,
            )
        )
    ).scalar_one_or_none()

    agent = None
    if existing:
        agent = await session.get(User, existing.agent_user_id)
    elif property_id:
        prop = (
            await session.execute(
                _select(Property).where(
                    Property.id == property_id,
                    Property.company_id == client.company_id,
                    Property.status == PropertyStatus.active,
                )
            )
        ).scalar_one_or_none()
        if prop:
            agent = await session.get(User, prop.agent_id)

    if agent is None:
        # Сначала ищем агента; если в компании его нет (частый случай —
        # только директор), лид уходит директору, а не пропадает молча.
        for role in (UR.agent, UR.director):
            agent = (
                await session.execute(
                    _select(User).where(
                        User.company_id == client.company_id,
                        User.role == role,
                        User.is_blocked == False,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if agent:
                break

    if not agent:
        import structlog
        structlog.get_logger().warning(
            "hot_lead_no_recipient", client_id=client.id, company_id=client.company_id
        )
        return

    if not existing:
        session.add(
            LeadAssignment(
                client_user_id=client.id,
                agent_user_id=agent.id,
                property_id=property_id,
                status=LeadStatus.new,
                notes=qualification.get("summary", ""),
            )
        )
        await session.commit()

    from html import escape as _esc

    score = qualification.get("qualification_score", 0)
    budget_min = qualification.get("budget_min_usd")
    budget_max = qualification.get("budget_max_usd")
    budget = f"${budget_min}-${budget_max}" if budget_min and budget_max else "-"
    districts = _esc(", ".join(qualification.get("preferred_districts") or []) or "-")
    rooms = ", ".join(str(r) for r in (qualification.get("preferred_rooms") or [])) or "-"
    phone = client_phone or client.phone or "-"
    username = f"@{client.username}" if client.username else "-"
    is_instagram = (client.telegram_user_id or 0) < 0
    source = "Instagram" if is_instagram else "Telegram"

    # Имя/резюме экранируем: имя из Instagram может содержать < > & —
    # без экранирования Telegram отклонит HTML и агент НЕ получит лид.
    msg = t(
        "hot_lead_notify",
        client_name=_esc(client.full_name or client.username or "Anonim"),
        score=score,
        budget=budget,
        districts=districts,
        rooms=rooms,
        timeline=qualification.get("purchase_timeline") or "-",
        payment_method=qualification.get("payment_method") or "-",
        summary=_esc(qualification.get("summary") or "-"),
    )
    msg += f"\n\nManba: {source}\nTelefon: {phone}"
    if not is_instagram:
        msg += f"\nTelegram: {_esc(username)}"

    try:
        await bot.send_message(agent.telegram_user_id, msg, parse_mode="HTML")
    except Exception as exc:
        import structlog
        structlog.get_logger().warning(
            "hot_lead_notify_failed", agent_id=agent.id, error=str(exc)
        )
