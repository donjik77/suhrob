"""
AI Service — wraps OpenRouter API for all AI-powered features.

Uses the OpenAI-compatible endpoint at https://openrouter.ai/api/v1.
Set OPENROUTER_API_KEY and OPENROUTER_MODEL in your .env file.
"""
import json
import re
import time
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


# Таймаут на служебные вызовы. Без него AsyncOpenAI ждёт до 600 секунд по
# умолчанию — а на бесплатных моделях OpenRouter очередь бывает именно такой.
# Один залипший вызов держал весь ответ клиенту.
_CHAT_TIMEOUT_SECONDS = 20


async def _chat(messages: list[dict], max_tokens: int = 512,
                model: str | None = None,
                timeout: float = _CHAT_TIMEOUT_SECONDS) -> str:
    """Send a chat request and return the response text."""
    client = _client()
    response = await client.chat.completions.create(
        model=model or settings.OPENROUTER_MODEL,
        max_tokens=max_tokens,
        messages=messages,
        timeout=timeout,
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
      client_name, client_gender, promo_code,
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
- client_name: mijozning ismi, agar suhbatda aytilgan bo'lsa (null yoki "Sardor")
- client_gender: "male"/"female"/null (ismdan yoki murojaatdan aniqlanadi)
- promo_code: agar assistant SUHROB-XXXX ko'rinishidagi promokod bergan bo'lsa,
  o'sha kodni qaytaring (null yoki "SUHROB-7K4F"). Yangi kod O'YLAB TOPMANG.

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
  "client_name": null,
  "client_gender": null,
  "promo_code": null,
  "qualification_score": 0,
  "summary": ""
}}"""

    try:
        # ЯВНО на MAIN_MODEL, а не на settings.OPENROUTER_MODEL: дефолт там —
        # бесплатная reasoning-модель, которая стоит в очереди OpenRouter и
        # гоняет длинный chain-of-thought ради JSON на 12 полей. Это была
        # основная причина "бот стал долго отвечать".
        text = await _chat([{"role": "user", "content": prompt}],
                           max_tokens=512, model=MAIN_MODEL)
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            return json.loads(json_match.group())
    except Exception as exc:
        logger.warning("ai_qualify_failed", error=str(exc))

    return {
        "budget_min_usd": None, "budget_max_usd": None,
        "preferred_districts": [], "preferred_rooms": [],
        "property_type": None, "purchase_timeline": None,
        "payment_method": None,
        "client_name": None, "client_gender": None, "promo_code": None,
        "qualification_score": 0,
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


# ─── Модель ──────────────────────────────────────────────────────────────────
# Раньше здесь было ДВЕ модели с роутингом, причём имена были перепутаны:
# "SMART" (Haiku) включался на СЛОЖНЫХ диалогах, а сильная модель — на
# простых. Чем глубже воронка, тем хуже работал бот, плюс характер менялся
# посреди разговора. Теперь одна модель на весь диалог.
#
# Haiku 4.5 выбран потому, что он дешевле Gemini Flash, лучше следует
# длинному промпту и поддерживает явное кэширование (см. chat_with_client).
MAIN_MODEL = "google/gemini-3-flash-preview"

# Оставлены для обратной совместимости — на них могут ссылаться другие модули
FAST_MODEL = MAIN_MODEL
SMART_MODEL = MAIN_MODEL


# ─── Районы: берём РЕАЛЬНЫЕ значения из базы ─────────────────────────────────
# Агент при добавлении объекта сам указывает район, комнаты и цену — по ним
# построен индекс ix_properties_search, и именно они являются источником
# истины для поиска. Поэтому не выдумываем свой список названий, а
# подтягиваем то, что реально лежит в location_district.

_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}


def _normalize(text: str) -> str:
    """Кириллица -> латиница, без апострофов и регистра.

    Клиент пишет "Гагарин", агент в базе — "Gagarin", кто-то ещё
    "Bogishamol" без апострофа. Без нормализации фильтр по району молча
    не срабатывал, запрос уходил без условия, и база отдавала случайные
    объекты — отсюда были промахи с Мотридом вместо Гагарина.
    """
    out = []
    for ch in text.lower():
        out.append(_CYR_TO_LAT.get(ch, ch))
    return "".join(out).replace("'", "").replace("`", "").replace("ʻ", "")


# Кэш районов, КЛЮЧ — company_id: {company_id: (время загрузки, {норм: как_в_базе})}
#
# Раньше это был один общий кортеж на весь процесс. BotManager держит боты
# всех компаний в ОДНОМ процессе, поэтому первая компания, для которой
# отработала load_districts, на 10 минут забивала кэш остальным: район
# подставлялся от чужой компании, и совпадение зависело от того, чей запрос
# прогрел кэш последним. Отсюда было "раньше работало, теперь через раз путает".
_districts_cache: dict[int, tuple[float, dict[str, str]]] = {}
_DISTRICTS_TTL = 600  # 10 минут — новые районы появляются нечасто


def reset_districts_cache(company_id: int | None = None) -> None:
    """Сбрасывает кэш районов (весь или одной компании). Нужен тестам."""
    if company_id is None:
        _districts_cache.clear()
    else:
        _districts_cache.pop(int(company_id), None)


async def load_districts(company_id: int, session) -> dict[str, str]:
    """Тянет из базы уникальные районы компании. Результат кэшируется."""
    now = time.time()
    key = int(company_id or 0)
    cached_at, cached = _districts_cache.get(key, (0.0, {}))
    if cached and now - cached_at < _DISTRICTS_TTL:
        return cached

    from sqlalchemy import select
    from src.db.models import Property, PropertyStatus

    rows = await session.execute(
        select(Property.location_district)
        .where(
            Property.company_id == company_id,
            Property.status == PropertyStatus.active,
        )
        .distinct()
    )
    mapping: dict[str, str] = {}
    for (name,) in rows:
        if name and name.strip():
            mapping[_normalize(name.strip())] = name.strip()

    _districts_cache[key] = (now, mapping)
    return mapping


async def extract_district(
    message: str, history: list, company_id: int, session
) -> str | None:
    """
    Ищет район в сообщении, сверяясь с реальными значениями из базы.
    Сначала текущее сообщение, потом история клиента.
    """
    districts = await load_districts(company_id, session)
    if not districts:
        return None

    # Длинные названия проверяем первыми, иначе "Amir Temur" перебьётся
    # каким-нибудь коротким совпадением
    keys = sorted(districts, key=len, reverse=True)

    def _find(text: str) -> str | None:
        norm = _normalize(text)
        for key in keys:
            if key and key in norm:
                return districts[key]
        return None

    found = _find(message)
    if found:
        return found

    for msg in reversed(history):
        if msg.get("role") == "user":
            found = _find(msg.get("content", ""))
            if found:
                return found
    return None


def is_complex(message: str, history_len: int) -> bool:
    """
    Утилита для логов/аналитики. ВЫБОР МОДЕЛИ БОЛЬШЕ НЕ ЗАВИСИТ от неё —
    модель одна на весь диалог.
    """
    return history_len > 10 or len(message) > 100


def extract_price(message: str, history: list) -> float | None:
    text = message.lower().replace(",", "")

    # Явные "ming" / "50k" — умножаем на 1000
    m = re.search(r"(\d+)\s*ming", text) or re.search(r"(\d+)\s*k\b", text)
    if m:
        val = float(m.group(1)) * 1000
        if 5000 < val < 2_000_000:
            return val

    # Просто число: $60000 или 60000.
    # ВАЖНО: раньше здесь стояла проверка `if "k" in text` — она умножала
    # на 1000 из-за буквы "k" в обычных словах ("kerak", "kvartira"),
    # и 45000 превращалось в 45 миллионов. Фильтр по цене отваливался.
    m = re.search(r"\$\s*(\d+)", text) or re.search(r"\b(\d{4,6})\b", text)
    if m:
        val = float(m.group(1))
        if 5000 < val < 2_000_000:
            return val

    return None


def extract_rooms(message: str, history: list) -> int | None:
    m = re.search(r"(\d)\s*xona", message.lower())
    if m:
        return int(m.group(1))
    return None


async def search_properties(
    company_id: int,
    district: str | None,
    price_max: float | None,
    rooms: int | None,
    session,
    limit: int = 3,
) -> list:
    """
    Единственный поиск объектов под запрос клиента.

    Вынесен отдельно, потому что нужен в двух местах: build_properties_context
    (текст для модели) и Instagram-мост (там модель НЕ печатает [CARD:ID],
    поэтому какие объекты показывать по запросу "покажите фото" мост должен
    знать сам, а не выуживать из ответа модели).
    """
    from sqlalchemy import select, or_
    from src.db.models import Property, PropertyStatus

    q = select(Property).where(
        Property.company_id == company_id,
        Property.status == PropertyStatus.active,
    )

    if district:
        # Ищем и в районе, и в адресе: "Gagarin" в Самарканде — это улица,
        # в location_district её может не быть вовсе
        q = q.where(or_(
            Property.location_district.ilike(f"%{district}%"),
            Property.location_address.ilike(f"%{district}%"),
        ))
    if price_max:
        q = q.where(Property.price_usd <= price_max)
    if rooms:
        q = q.where(Property.rooms == rooms)

    result = await session.execute(q.limit(limit))
    return list(result.scalars())


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

    # ── конкретная карточка ──────────────────────────────────────────────
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
            text = (
                selected.custom_text
                or selected.description
                or selected.title
                or ""
            )
            return (
                "Tanlangan obyekt konteksti:\n\n"
                f"CARD_ID:{selected.id} | Tuman: {selected.location_district} | "
                f"Manzil: {selected.location_address or '—'} | "
                f"{selected.rooms} xona | ${selected.price_usd:,.0f}\n"
                f"{text}\n\n"
                "Mijoz aynan shu obyekt haqida so'rayapti. "
                "Tayyor tavsifdan foydalanib javob bering."
            )

    # ── поиск вариантов ──────────────────────────────────────────────────
    props = await search_properties(
        company_id, district, price_max, rooms, session, limit=3
    )

    if not props:
        if district:
            # Явно запрещаем модели подсовывать объекты из другого района
            return (
                f"DIQQAT: {district} bo'yicha mos uy TOPILMADI.\n"
                f"Boshqa joydagi uyni {district} deb KO'RSATMA — bu yolg'on.\n"
                "Mijozga halol ayt: shu joyda hozir yo'q, va boshqa tuman taklif qil."
            )
        return "Hozircha bu parametrlarda mos uy yo'q."

    lines = []
    for p in props:
        text = (p.custom_text or p.description or p.title or "")
        # Структурные поля идут ПЕРВЫМИ и отдельно от свободного текста.
        # Раньше в контекст уходил только custom_text, а адрес лежал внутри
        # него глубоко — при обрезке модель теряла район и выбирала карточки
        # вслепую. Теперь обрезка описания на это не влияет.
        lines.append(
            f"CARD_ID:{p.id} | Tuman: {p.location_district} | "
            f"Manzil: {p.location_address or '—'} | "
            f"{p.rooms} xona | ${p.price_usd:,.0f}\n"
            f"{text[:300]}"
        )

    header = "Topilgan obyektlar"
    if district:
        header = f"Topilgan obyektlar ({district} bo'yicha)"

    return (
        f"{header}. FAQAT shu ro'yxatdagi CARD_ID larni ishlat:\n\n"
        + "\n\n---\n\n".join(lines)
    )


# ─── Профиль клиента: имя / пол / промокод внутри notes ──────────────────────
# В таблице client_profiles НЕТ колонок под client_name, client_gender и
# promo_code — есть только notes (Text). Раньше qualify_client исправно
# извлекал эти три поля, а оба upsert-а (Telegram и Instagram) их МОЛЧА
# выбрасывали: notes целиком перезаписывался значением summary. Поэтому
# промокод жил ровно столько, сколько держалось окно истории [-12:], и на
# длинном диалоге бот выдавал новый код.
#
# Чиним без миграции: notes хранит JSON {summary, client_name, client_gender,
# promo_code}. Старые строки (просто текст) читаются как summary.

_NOTES_FIELDS = ("client_name", "client_gender", "promo_code")


def unpack_profile_notes(notes: str | None) -> dict:
    """notes -> {summary, client_name, client_gender, promo_code}."""
    empty = {"summary": "", "client_name": None,
             "client_gender": None, "promo_code": None}
    if not notes:
        return empty
    text = notes.strip()
    if not text.startswith("{"):
        # Строка, записанная до этого фикса — это просто summary
        return {**empty, "summary": text}
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return {**empty, "summary": text}
    if not isinstance(data, dict):
        return {**empty, "summary": text}
    return {
        "summary": data.get("summary") or "",
        **{f: data.get(f) for f in _NOTES_FIELDS},
    }


def merge_profile_notes(existing_notes: str | None, data: dict) -> str:
    """
    Сливает новые данные квалификации с уже сохранёнными.

    КЛЮЧЕВОЕ: пустое/None значение НЕ затирает сохранённое. Если модель на
    этом шаге не увидела промокод в окне истории — он остаётся тем же,
    а не обнуляется.
    """
    merged = unpack_profile_notes(existing_notes)
    if data.get("summary"):
        merged["summary"] = data["summary"]
    for field in _NOTES_FIELDS:
        value = data.get(field)
        if value:
            merged[field] = value
    return json.dumps(merged, ensure_ascii=False)


def profile_summary(notes: str | None) -> str:
    """Человекочитаемое резюме из notes — для уведомления агенту."""
    return unpack_profile_notes(notes).get("summary") or ""


def profile_to_context(profile_row) -> dict:
    """
    ORM-строка ClientProfile -> dict для chat_with_client.

    Один источник истины для обоих каналов: раньше Telegram и Instagram
    собирали этот словарь каждый по-своему, и ни один из них не клал в него
    имя/пол/промокод — из-за чего format_client_profile о них не знал.
    """
    if profile_row is None:
        return {}
    notes = unpack_profile_notes(getattr(profile_row, "notes", None))
    return {
        "budget_min_usd": profile_row.budget_min_usd,
        "budget_max_usd": profile_row.budget_max_usd,
        "preferred_districts": profile_row.preferred_districts or [],
        "preferred_rooms": profile_row.preferred_rooms,
        "purchase_timeline": profile_row.purchase_timeline,
        "payment_method": profile_row.payment_method,
        "qualification_score": profile_row.qualification_score,
        "client_name": notes.get("client_name"),
        "client_gender": notes.get("client_gender"),
        "promo_code": notes.get("promo_code"),
    }


async def format_client_profile(profile: dict) -> str:
    if not profile:
        return "Yangi mijoz. Ism va jins NOMA'LUM — avval tanishib ol."
    parts = []

    # ИМЯ, ПОЛ, ПРОМОКОД — без них новый промпт не работает: бот заново
    # спрашивает имя и генерирует новый промокод каждый раз.
    if profile.get("client_name"):
        parts.append(f"Ismi: {profile['client_name']}")
    if profile.get("client_gender"):
        gender_uz = {"male": "erkak", "female": "ayol"}.get(
            profile["client_gender"], profile["client_gender"]
        )
        parts.append(f"Jinsi: {gender_uz}")
    if profile.get("promo_code"):
        parts.append(
            f"BERILGAN PROMOKOD: {profile['promo_code']} "
            "(YANGI KOD YARATMA — faqat shuni ishlat)"
        )

    if profile.get("budget_min_usd"):
        parts.append(f"Byudjet: ${profile['budget_min_usd']:,}–${profile.get('budget_max_usd') or '?'}")
    if profile.get("preferred_districts"):
        parts.append(f"Tuman: {', '.join(profile['preferred_districts'])}")
    if profile.get("preferred_rooms"):
        parts.append(f"Xonalar: {profile['preferred_rooms']}")
    if profile.get("payment_method"):
        parts.append(f"To'lov: {profile['payment_method']}")
    if profile.get("purchase_timeline"):
        parts.append(f"Muddat: {profile['purchase_timeline']}")

    if not profile.get("client_name"):
        parts.append("Ism hali NOMA'LUM — avval tanishib ol")

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
    channel: str = "telegram",
) -> str:
    """
    Основной диалог с клиентом. Одна модель (MAIN_MODEL) на весь разговор.

    channel: "telegram" | "instagram" — определяет правила длины ответа и
    способ показа объектов (карточка [CARD:ID] против текстового списка).
    """
    import httpx
    from src.services.ai_prompts import (
        SYSTEM_PROMPT, CACHE_MARKER, channel_rules,
    )

    district = await extract_district(
        user_message, conversation_history, company_id, session
    )
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

    # ── Кэширование промпта ──────────────────────────────────────────────
    # Системный промпт (~4000 токенов персонажа, правил и примеров)
    # одинаков во всех запросах, но отправляется заново каждый раз — это
    # и есть основная статья расходов. Режем его надвое: статику помечаем
    # cache_control (повторные чтения ~в 10 раз дешевле), а динамику
    # (объекты, профиль, агенты) шлём как есть — она меняется постоянно.
    # Правила канала лежат в динамике: они разные для Telegram и Instagram,
    # и держать из-за них две копии кэшируемой статики смысла нет.
    fields = dict(
        properties_context=properties,
        client_profile=profile_text,
        agents_contacts=agents_text,
        channel_rules=channel_rules(channel),
    )
    if CACHE_MARKER in SYSTEM_PROMPT:
        static_part, _tail = SYSTEM_PROMPT.split(CACHE_MARKER, 1)
        dynamic_part = (CACHE_MARKER + _tail).format(**fields)
    else:
        # Промпт отредактировали и маркер пропал — работаем без кэша
        static_part = ""
        dynamic_part = SYSTEM_PROMPT.format(**fields)

    system_blocks = []
    if static_part:
        system_blocks.append({
            "type": "text",
            "text": static_part,
            "cache_control": {"type": "ephemeral"},
        })
    system_blocks.append({"type": "text", "text": dynamic_part})

    model = MAIN_MODEL

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
                    # 0.3 было слишком низко — модель копировала примеры из
                    # промпта дословно. 0.6 — компромисс: живой текст, но
                    # аккуратный выбор CARD_ID.
                    "temperature": 0.6,
                    "max_tokens": 700,
                    # Без этого Gemini тратил почти весь лимит на внутренние
                    # рассуждения, и ответ обрывался на полуслове
                    "reasoning": {"enabled": False},
                    "messages": [
                        {"role": "system", "content": system_blocks},
                        *conversation_history[-12:],
                        {"role": "user", "content": user_message},
                    ],
                },
            )
            data = response.json()

        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            logger.warning("ai_reply_truncated", model=model,
                           usage=data.get("usage"))
        return choice["message"]["content"]
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
