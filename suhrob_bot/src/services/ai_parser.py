import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

PARSE_PROMPT = """Quyidagi matndan ko'chmas mulk ma'lumotlarini ajrat.

Matn:
{text}

Qoidalar:
- property_type: "apartment" (kvartira/xonadon/flat/квартира), "house" (hovli/uy/dom/дом), "commercial" (tijorat/ofis/do'kon/магазин/офис)
- district: tuman yoki mahalla nomi (masalan: Mirzo-Ulug'bek, Yunusobod, Chilonzor)
- address: aniq ko'cha, uy raqami yoki null
- rooms: xonalar soni butun son yoki null
- floor: qaysi qavatda butun son yoki null
- total_floors: uyning jami qavatlar soni butun son yoki null
- area_sqm: maydon m² da raqam yoki null
- price_usd: narx FAQAT dollar da raqam (belgilar yo'q, vergul yo'q) yoki null
- description: qolgan barcha ma'lumotlar (tamirlash, holat, aloqa, boshqa)

Agar qiymat topilmasa null qo'y.
FAQAT JSON qaytaring, hech qanday qo'shimcha matn yo'q:
{{"property_type": ..., "district": ..., "address": ..., "rooms": ..., "floor": ..., "total_floors": ..., "area_sqm": ..., "price_usd": ..., "description": ...}}"""


async def parse_property_from_text(text: str) -> dict:
    """Parse property data from free-form text. Uses Claude AI if API key is set, else regex fallback."""
    from src.config import settings

    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                messages=[{"role": "user", "content": PARSE_PROMPT.format(text=text)}],
            )
            raw = message.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            parsed = json.loads(raw)
            logger.info("AI parsing successful")
            return _normalize(parsed)
        except Exception as exc:
            logger.error(f"AI parsing failed, using regex fallback: {exc}")

    return _regex_fallback(text)


def _normalize(parsed: dict) -> dict:
    """Ensure all expected keys exist and types are correct."""
    result = {
        "property_type": parsed.get("property_type"),
        "district": parsed.get("district"),
        "address": parsed.get("address"),
        "rooms": _to_int(parsed.get("rooms")),
        "floor": _to_int(parsed.get("floor")),
        "total_floors": _to_int(parsed.get("total_floors")),
        "area_sqm": _to_float(parsed.get("area_sqm")),
        "price_usd": _to_int(parsed.get("price_usd")),
        "description": parsed.get("description"),
    }
    if result["property_type"] not in ("apartment", "house", "commercial"):
        result["property_type"] = None
    return result


def _regex_fallback(text: str) -> dict:
    result = {
        "property_type": None,
        "district": None,
        "address": None,
        "rooms": None,
        "floor": None,
        "total_floors": None,
        "area_sqm": None,
        "price_usd": None,
        "description": text,
    }
    lower = text.lower()

    # Price: 65000$ / $65,000 / 65 000 usd / 65000 dollar
    for pat in [
        r'\$\s*([\d\s,]+)',
        r'([\d\s,]+)\s*(?:\$|usd|dollar|долл)',
        r'narx[i:]?\s*([\d\s,]+)',
    ]:
        m = re.search(pat, lower)
        if m:
            val = _to_int(m.group(1).replace(" ", "").replace(",", ""))
            if val and val > 1000:
                result["price_usd"] = val
                break

    # Rooms
    m = re.search(r'(\d+)\s*(?:xona(?:li)?|kom(?:nat)?|xonadon)', lower)
    if m:
        result["rooms"] = int(m.group(1))

    # Floor N/M
    m = re.search(r'(\d+)\s*/\s*(\d+)\s*(?:qavat|этаж)?', text)
    if m:
        result["floor"] = int(m.group(1))
        result["total_floors"] = int(m.group(2))
    else:
        m = re.search(r'(\d+)(?:-?(?:chi|нчи|nchi))?\s*qavat', lower)
        if m:
            result["floor"] = int(m.group(1))

    # Area
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:m²|m2|kv\.?m|кв\.?м|квм)', lower)
    if m:
        result["area_sqm"] = float(m.group(1).replace(",", "."))

    # Type
    if any(w in lower for w in ["kvartira", "xonadon", "flat", "квартира", "апартамент"]):
        result["property_type"] = "apartment"
    elif any(w in lower for w in ["hovli", "dom", "дом", "house", "cottage"]):
        result["property_type"] = "house"
    elif any(w in lower for w in ["tijorat", "офис", "магазин", "ofis", "do'kon", "склад"]):
        result["property_type"] = "commercial"

    return result


def _to_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(str(val).replace(" ", "").replace(",", "").split(".")[0])
    except (ValueError, TypeError):
        return None


def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except (ValueError, TypeError):
        return None
