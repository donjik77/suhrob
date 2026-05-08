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
    prompt = f"""Sen professional ko'chmas mulk agentisan. Quyidagi ma'lumotlar asosida sotuvchi tavsif yoz (o'zbek tilida, lotin yozuvida).

Ma'lumotlar:
- Tur: {data.get('property_type', '')}
- Tuman: {data.get('district', '')}
- Manzil: {data.get('address', 'ko\'rsatilmagan')}
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
