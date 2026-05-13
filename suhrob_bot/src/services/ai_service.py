"""
AI Service — wraps OpenRouter API for all AI-powered features.

Uses the OpenAI-compatible endpoint at https://openrouter.ai/api/v1.
Set OPENROUTER_API_KEY and OPENROUTER_MODEL in your .env file.
"""
import json
import re
import structlog
from typing import Optional

from openai import AsyncOpenAI

from src.config import settings

logger = structlog.get_logger()

_FALLBACK_DESCRIPTION = "Ushbu ko'chmas mulk haqida batafsil ma'lumot uchun agent bilan bog'laning."


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )


async def _chat(messages: list[dict], max_tokens: int = 512) -> str:
    """Send a chat request and return the response text."""
    client = _client()
    response = await client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.choices[0].message.content.strip()


async def generate_property_description(data: dict) -> str:
    """Generate a selling property description in Uzbek (Latin) from raw fields."""
    addr = data.get("address", "ko'rsatilmagan")
    prompt = f"""Sen professional ko'chmas mulk agentisan. Quyidagi ma'lumotlar asosida sotuvchi tavsif yoz (o'zbek tilida, lotin yozuvida).

Ma'lumotlar:
- Tur: {data.get('property_type', '')}
- Tuman: {data.get('district', '')}
- Manzil: {addr}
- Xonalar: {data.get('rooms', '')}
- Qavat: {data.get('floor', '')}/{data.get('total_floors', '')}
- Maydon: {data.get('area', '')} m²
- Narx: ${data.get('price', '')}
- Xususiyatlari: {', '.join(data.get('features', []))}
- Qo'shimcha: {data.get('keywords', '')}

Talablar:
- 4-6 gap
- Sotuvchi, suvli, keraksiz so'zlarsiz
- Asosiy afzalliklarni ko'rsat
- Faqat ma'lumotlarda bor narsalarni yoz
- Faqat tavsifni yoz, kirish yoki xulosa qo'shma"""

    try:
        return await _chat([{"role": "user", "content": prompt}], max_tokens=512)
    except Exception as exc:
        logger.warning("ai_description_failed", error=str(exc))
        return _FALLBACK_DESCRIPTION


async def evaluate_photo_quality(file_path: str) -> float:
    """Score a property photo 0-10 using vision model. Returns 5.0 on error."""
    import base64
    import pathlib

    try:
        path = pathlib.Path(file_path)
        if not path.exists():
            return 5.0
        image_bytes = path.read_bytes()
        suffix = path.suffix.lower().lstrip(".")
        return await _score_image_bytes(image_bytes, suffix)
    except Exception as exc:
        logger.warning("ai_photo_eval_failed", error=str(exc))
        return 5.0


async def evaluate_photo_quality_from_bytes(image_bytes: bytes, ext: str = "jpg") -> float:
    """Score a property photo (raw bytes) 0-10. Returns 5.0 on error."""
    try:
        return await _score_image_bytes(image_bytes, ext)
    except Exception as exc:
        logger.warning("ai_photo_eval_bytes_failed", error=str(exc))
        return 5.0


async def _score_image_bytes(image_bytes: bytes, ext: str) -> float:
    import base64
    media_type = f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
    client = _client()
    response = await client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{image_data}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Rate this real estate photo quality 0-10.\n"
                            "Criteria: lighting (4pts), composition/framing (3pts), "
                            "cleanliness/no clutter (2pts), visible room size (1pt).\n"
                            "Reply with a single number only, one decimal place."
                        ),
                    },
                ],
            }
        ],
    )
    text = response.choices[0].message.content.strip()
    match = re.search(r"\d+(?:\.\d)?", text)
    return float(match.group()) if match else 5.0


async def qualify_client(conversation: list[dict]) -> dict:
    """
    Analyse a conversation list ([{role, content}, ...]) and return a dict:
    {
      budget_min_usd, budget_max_usd, preferred_districts, preferred_rooms,
      property_type, purchase_timeline, payment_method,
      qualification_score, summary
    }
    Returns safe defaults on error.
    """
    messages_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in conversation
    )
    prompt = f"""Siz ko'chmas mulk bo'yicha mutaxasssissiz. Quyidagi suhbatni tahlil qiling va mijozning ma'lumotlarini JSON formatida qaytaring.

Suhbat:
{messages_text}

Suhbatdan quyidagilarni ajratib oling (agar aytilgan bo'lsa):
- budget_min_usd: minimal byudjet USD da (null yoki raqam)
- budget_max_usd: maksimal byudjet USD da (null yoki raqam)
- preferred_districts: afzal tumanlar ro'yxati ([] yoki ["Tuman1", ...])
- preferred_rooms: afzal xonalar soni ([2, 3] kabi)
- property_type: "apartment"/"house"/"commercial"/null
- purchase_timeline: "urgent"/"1-3months"/"3-6months"/"just_looking"/null
- payment_method: "cash"/"mortgage"/"installment"/null

Shuningdek qualification_score hisoblang (0-100):
- +30: byudjet aniq ko'rsatilgan
- +25: muddati 3 oydan kam
- +20: to'lov usuli ko'rsatilgan (ayniqsa naqd)
- +15: tuman ko'rsatilgan
- +10: konkret obyektga qiziqish

summary: suhbatning qisqacha xulosasi o'zbek tilida (1-2 gap)

Faqat JSON qaytaring, boshqa hech narsa:
{{
  "budget_min_usd": null,
  "budget_max_usd": null,
  "preferred_districts": [],
  "preferred_rooms": [],
  "property_type": null,
  "purchase_timeline": null,
  "payment_method": null,
  "qualification_score": 0,
  "summary": ""
}}"""

    try:
        text = await _chat([{"role": "user", "content": prompt}], max_tokens=512)
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return json.loads(json_match.group())
    except Exception as exc:
        logger.warning("ai_qualify_failed", error=str(exc))

    return {
        "budget_min_usd": None, "budget_max_usd": None,
        "preferred_districts": [], "preferred_rooms": [],
        "property_type": None, "purchase_timeline": None,
        "payment_method": None, "qualification_score": 0,
        "summary": "",
    }


async def answer_property_question(question: str, property_data: dict) -> str:
    """Answer a client question about a specific property."""
    features = ", ".join(property_data.get("features") or [])
    prompt = f"""Siz ko'chmas mulk kompaniyasining AI yordamchisisiz. Mijoz quyidagi obyekt haqida savol bermoqda.

Obyekt ma'lumotlari:
- Sarlavha: {property_data.get('title', '')}
- Tur: {property_data.get('property_type', '')}
- Tuman: {property_data.get('district', '')}
- Narx: ${property_data.get('price_usd', '')}
- Xonalar: {property_data.get('rooms', '')}
- Qavat: {property_data.get('floor', '')}/{property_data.get('total_floors', '')}
- Maydon: {property_data.get('area_sqm', '')} m²
- Xususiyatlari: {features}
- Tavsif: {property_data.get('description', '')}

Mijoz savoli: {question}

Qoidalar:
- O'zbek tilida javob bering (lotin yozuvi)
- Faqat ma'lumotlarda bor narsalarni ayting
- Bilmasangiz: "Bu savol uchun agent bilan bog'laning"
- Qisqa va aniq (2-3 gap)"""

    try:
        return await _chat([{"role": "user", "content": prompt}], max_tokens=256)
    except Exception as exc:
        logger.warning("ai_property_answer_failed", error=str(exc))
        return "Bu savol uchun aniqroq ma'lumot uchun agent bilan bog'laning."


async def run_consultation(
    messages: list[dict],
    company_name: str,
    client_profile: Optional[dict],
    available_properties_summary: str,
) -> str:
    """
    Run a free-form AI consultation session.
    messages: [{role: "user"|"assistant", content: str}, ...]
    Returns the assistant reply text.
    """
    system_content = f"""Siz "{company_name}" ko'chmas mulk kompaniyasining AI-konsultantisiz (O'zbekiston).
O'zbek tilida (lotin yozuvi), muloyim va professional muloqot qiling.

Vazifalaringiz:
1. Mijozning ko'chmas mulk savollari javob bering
2. Mijozni kvalifikatsiya qiling: byudjet, muddat, to'lov usuli, jiddiylik
3. Bazadagi mos variantlarni taklif qiling
4. Jiddiy qiziqish bo'lsa — agentga ulang

Mijoz profili:
{json.dumps(client_profile or {}, ensure_ascii=False, indent=2)}

Mavjud obyektlar xulosasi:
{available_properties_summary}

Qoidalar:
- Bazada yo'q obyektlarni o'ylab topmang
- Bazada yo'q narxlarni aytmang
- Mijoz jiddiy bo'lsa (byudjet aniq, muddat <3 oy) — agentga ulanishni taklif qiling
- Faqat ko'rmoqda bo'lsa — muloyimlik bilan kontakt ma'lumotlarini so'rang"""

    full_messages = [{"role": "system", "content": system_content}] + messages

    try:
        return await _chat(full_messages, max_tokens=512)
    except Exception as exc:
        logger.warning("ai_consultation_failed", error=str(exc))
        return "Kechirasiz, hozir AI xizmati vaqtincha ishlamayapti. Iltimos, agentga to'g'ridan-to'g'ri murojaat qiling."


def generate_property_title(data: dict) -> str:
    """Generate a short readable property title (no AI call needed)."""
    ptype_map = {"apartment": "Kvartira", "house": "Hovli", "commercial": "Tijorat"}
    ptype = ptype_map.get(data.get("property_type", ""), "Uy")
    district = data.get("district", "")
    rooms = data.get("rooms")
    parts = [ptype]
    if rooms and str(rooms) != "any":
        parts.append(f"{rooms} xona")
    if district:
        parts.append(district)
    return " — ".join(parts)


# ─── Smart/Fast model routing ────────────────────────────────────────────────

FAST_MODEL = "google/gemini-2.5-flash"
SMART_MODEL = "anthropic/claude-haiku-4-5"

_DISTRICTS = [
    "mirzo ulug'bek", "yunusobod", "chilonzor", "yashnobod",
    "sergeli", "yakkasaroy", "mirobod", "shayxontohur",
    "vokzal", "register", "lola", "gagarin",
    "samarqand", "kattaqo'rg'on", "urgut", "bulungur",
]


def is_complex(message: str, history_len: int) -> bool:
    if history_len > 10:
        return True
    if len(message) > 100:
        return True
    simple_words = ["narxi", "qancha", "xona", "manzil", "qavat", "maydon"]
    if any(w in message.lower() for w in simple_words) and len(message) < 50:
        return False
    return False


def extract_district(message: str, history: list) -> str | None:
    text = message.lower()
    for d in _DISTRICTS:
        if d in text:
            return d.title()
    for msg in reversed(history):
        if msg.get("role") == "user":
            t = msg.get("content", "").lower()
            for d in _DISTRICTS:
                if d in t:
                    return d.title()
    return None


def extract_price(message: str, history: list) -> float | None:
    patterns = [
        r"(\d+)\s*ming",
        r"(\d+)k\b",
        r"\$(\d[\d,]+)",
        r"(\d{4,6})",
    ]
    text = message.lower().replace(",", "")
    for p in patterns:
        m = re.search(p, text)
        if m:
            val = float(m.group(1).replace(",", ""))
            if "ming" in text or "k" in text:
                val *= 1000
            if 5000 < val < 2_000_000:
                return val
    return None


def extract_rooms(message: str, history: list) -> int | None:
    m = re.search(r"(\d)\s*xona", message.lower())
    if m:
        return int(m.group(1))
    return None


async def build_properties_context(
    company_id: int,
    district: str | None,
    price_max: float | None,
    rooms: int | None,
    session,
    property_id: int | None = None,
) -> str:
    from sqlalchemy import select
    from src.db.models import Property, PropertyStatus

    if property_id:
        selected = (
            await session.execute(
                select(Property).where(
                    Property.id == property_id,
                    Property.company_id == company_id,
                    Property.status == PropertyStatus.active,
                )
            )
        ).scalar_one_or_none()
        if selected:
            return (
                "Tanlangan obyekt konteksti:\n"
                f"CARD_ID:{selected.id} | {selected.title} | {selected.property_type.value} | "
                f"{selected.location_district} | {selected.location_address or ''} | "
                f"{selected.rooms} xona | {selected.floor}/{selected.total_floors} qavat | "
                f"{selected.area_sqm} m² | ${selected.price_usd:,.0f} | "
                f"{selected.description or ''}\n\n"
                "Mijoz aynan shu obyekt haqida so'rayapti. "
                "Faqat shu ma'lumotlarga tayaning; yetishmaydigan ma'lumot uchun agentga ulashni taklif qiling."
            )

    q = select(Property).where(
        Property.company_id == company_id,
        Property.status == PropertyStatus.active,
    )
    if district:
        q = q.where(Property.location_district.ilike(f"%{district}%"))
    if price_max:
        q = q.where(Property.price_usd <= price_max)
    if rooms:
        q = q.where(Property.rooms == rooms)

    result = await session.execute(q.limit(5))
    props = list(result.scalars())

    if not props:
        return "Hozircha bu parametrlarda mos uy yo'q."

    lines = []
    for p in props:
        lines.append(
            f"CARD_ID:{p.id} | {p.property_type.value} | {p.location_district} | "
            f"{p.location_address or ''} | "
            f"{p.rooms} xona | {p.floor}/{p.total_floors} qavat | "
            f"{p.area_sqm} m² | ${p.price_usd:,.0f} | "
            f"{p.description[:120] if p.description else ''}"
        )
    return "\n".join(lines)


async def format_client_profile(profile: dict) -> str:
    if not profile:
        return "Yangi mijoz, ma'lumot yo'q."
    parts = []
    if profile.get("budget_min_usd"):
        parts.append(f"Byudjet: ${profile['budget_min_usd']:,}–${profile.get('budget_max_usd', '?')}")
    if profile.get("preferred_districts"):
        parts.append(f"Tuman: {', '.join(profile['preferred_districts'])}")
    if profile.get("preferred_rooms"):
        parts.append(f"Xonalar: {profile['preferred_rooms']}")
    if profile.get("payment_method"):
        parts.append(f"To'lov: {profile['payment_method']}")
    if profile.get("purchase_timeline"):
        parts.append(f"Muddat: {profile['purchase_timeline']}")
    return " | ".join(parts) if parts else "Parametrlar aniqlanmagan."


async def format_agents_contacts(company_id: int, session) -> str:
    from sqlalchemy import select
    from src.db.models import User, UserRole

    result = await session.execute(
        select(User).where(
            User.company_id == company_id,
            User.role.in_([UserRole.agent, UserRole.director]),
            User.is_blocked == False,
        )
    )
    agents = list(result.scalars())
    if not agents:
        return "Agent ma'lumotlari yo'q."
    lines = []
    for a in agents:
        line = f"\U0001f464 {a.full_name or 'Agent'}"
        if a.phone:
            line += f" — \U0001f4de {a.phone}"
        if a.username:
            line += f" (@{a.username})"
        lines.append(line)
    return "\n".join(lines)


async def chat_with_client(
    user_message: str,
    conversation_history: list[dict],
    client_profile: dict,
    company_id: int,
    session,
    property_id: int | None = None,
) -> str:
    """Fast model (Gemini Flash) для простых вопросов, Smart model (Haiku) для сложных."""
    import httpx
    from src.services.ai_prompts import SYSTEM_PROMPT

    district = extract_district(user_message, conversation_history)
    price_max = extract_price(user_message, conversation_history)
    rooms = extract_rooms(user_message, conversation_history)

    properties = await build_properties_context(
        company_id,
        district,
        price_max,
        rooms,
        session,
        property_id=property_id,
    )
    profile_text = await format_client_profile(client_profile)
    agents_text = await format_agents_contacts(company_id, session)

    system = SYSTEM_PROMPT.format(
        properties_context=properties,
        client_profile=profile_text,
        agents_contacts=agents_text,
    )

    model = SMART_MODEL if is_complex(user_message, len(conversation_history)) else FAST_MODEL

    try:
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://suhrob-house.uz",
                    "X-Title": "Suhrob HOUSE Bot",
                },
                json={
                    "model": model,
                    "temperature": 0.3,
                    "max_tokens": 600,
                    "messages": [
                        {"role": "system", "content": system},
                        *conversation_history[-10:],
                        {"role": "user", "content": user_message},
                    ],
                },
            )
            data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("chat_with_client_failed", model=model, error=str(exc))
        return "Kechirasiz, hozir texnik nosozlik bor. Iltimos, qaytadan urinib ko'ring."


async def generate_follow_up_message(client_name: str, district: str, budget_str: str, day: int) -> str:
    """Generate a personalised follow-up message for day 3, 7, or 14."""
    prompt = f"""Mijozga follow-up xabar yoz (o'zbek tilida, lotin yozuvi).
Mijoz ismi: {client_name}
Qidirilgan tuman: {district}
Byudjet: {budget_str}
Necha kundan keyin: {day}

Xabar qisqa, do'stona, bosimchisiz bo'lsin (2-3 gap).
Faqat xabar matnini yoz."""

    try:
        return await _chat([{"role": "user", "content": prompt}], max_tokens=200)
    except Exception as exc:
        logger.warning("ai_followup_failed", error=str(exc))
        return f"Salom, {client_name}! {district} tumanidagi yangi variantlar bor. Ko'rasizmi?"
