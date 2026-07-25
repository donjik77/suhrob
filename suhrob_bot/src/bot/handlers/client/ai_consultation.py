"""
AI consultation handler — free dialog with Claude for clients.
Triggered by main menu button or property card inline button.
"""
import re

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
_AGENT_CONNECT_RE = re.compile(
    r"(agent|makler|rieltor|bog'?la|boglan|bog'lan|aloqa|telefon|ko'rish|korish|uchrash)",
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
    qualification = data.get("qualification") or {}

    async with AsyncSessionFactory() as session:
        await session.execute(
            update(User)
            .where(User.id == db_user.id)
            .values(phone=phone)
        )
        await session.commit()
        db_user.phone = phone
        await _maybe_assign_hot_lead(
            session,
            db_user,
            qualification,
            message.bot,
            client_phone=phone,
            property_id=property_id,
        )

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
    needs_phone_for_agent = False

    # Save assistant reply
    async with AsyncSessionFactory() as session:
        session.add(ClientConversation(
            user_id=db_user.id,
            property_id=property_id,
            role="assistant",
            message=reply,
        ))
        await session.commit()

        # Re-qualify after every message
        all_history = history + [{"role": "assistant", "content": reply}]
        qualification = await ai_service.qualify_client(all_history)
        await _upsert_client_profile(session, db_user.id, qualification)

        # Auto-assign hot leads, but collect the client's phone before notifying agents.
        should_connect_agent = qualification.get("qualification_score", 0) >= 70 or wants_agent
        if should_connect_agent:
            if db_user.phone:
                await _maybe_assign_hot_lead(
                    session,
                    db_user,
                    qualification,
                    message.bot,
                    client_phone=db_user.phone,
                    property_id=property_id,
                )
            else:
                needs_phone_for_agent = True

    await message.answer(reply)
    await _send_ai_property_cards(message, db_user.company_id, property_card_ids)
    if needs_phone_for_agent:
        await state.set_state(ConsultState.waiting_phone_for_agent)
        await state.update_data(property_id=property_id, qualification=qualification)
        await message.answer(
            "Agent bilan bog'lash uchun telefon raqamingizni yuboring.",
            reply_markup=request_client_phone_kb(),
        )


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
        if data.get("summary"):
            existing.notes = data["summary"]
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
            notes=data.get("summary"),
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
