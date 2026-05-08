from decimal import Decimal
from typing import Optional

from src.db.models import Property, PropertyType
from src.utils.currency import usd_to_uzs
from locales.uz import t

PROPERTY_TYPE_ICONS = {
    PropertyType.apartment: "🏢",
    PropertyType.house: "🏡",
    PropertyType.commercial: "🏪",
}

PROPERTY_TYPE_LABELS = {
    PropertyType.apartment: "Kvartira",
    PropertyType.house: "Hovli",
    PropertyType.commercial: "Tijorat",
}

PRICE_RANGES = {
    (0, 30_000): "$0-30K",
    (30_000, 60_000): "$30-60K",
    (60_000, 100_000): "$60-100K",
    (100_000, 200_000): "$100-200K",
    (200_000, None): "$200K+",
}

FEATURE_LABELS: dict[str, str] = {
    "repair":          "🚿 Ta'mirli",
    "parking":         "🚗 Avtoturargoh",
    "garden":          "🌳 Hovli/Bog'",
    "pool":            "🏊 Basseyn",
    "ac":              "🌡 Konditsioner",
    "furniture":       "🪑 Mebelli",
    "elevator":        "🛗 Lift",
    "central_heating": "🔥 Markaziy isitish",
    "internet":        "🌐 Internet",
    "security":        "🛡 Xavfsizlik",
}


def format_property_card(prop: Property, rate: float) -> str:
    price_uzs = usd_to_uzs(prop.price_usd, rate)
    address_part = f", {prop.location_address}" if prop.location_address else ""

    floor_info = ""
    if prop.floor and prop.total_floors:
        floor_info = t("floor_info", floor=prop.floor, total_floors=prop.total_floors)
    elif prop.floor:
        floor_info = t("floor_info", floor=prop.floor, total_floors="?")

    area_info = ""
    if prop.area_sqm:
        area_info = t("area_info", area=prop.area_sqm)

    agent_name = ""
    if prop.agent:
        agent_name = prop.agent.full_name or prop.agent.username or str(prop.agent.telegram_user_id)

    features_block = ""
    if prop.features:
        lines = "\n".join(f"• {FEATURE_LABELS.get(f, f)}" for f in prop.features)
        features_block = f"\n✨ <b>Xususiyatlari:</b>\n{lines}\n"

    desc = prop.description or ""

    return t(
        "property_card",
        title=prop.title,
        district=prop.location_district,
        address=address_part,
        price_usd=f"{int(prop.price_usd):,}",
        price_uzs=price_uzs,
        rooms=prop.rooms,
        floor_info=floor_info,
        area_info=area_info,
        features=features_block,
        description=desc,
        agent_name=agent_name,
    )


def format_channel_post(prop: Property, rate: float) -> str:
    price_uzs = usd_to_uzs(prop.price_usd, rate)
    icon = PROPERTY_TYPE_ICONS.get(prop.property_type, "🏠")
    type_label = PROPERTY_TYPE_LABELS.get(prop.property_type, "Uy")

    floor_info = "—"
    if prop.floor and prop.total_floors:
        floor_info = f"🏢 {prop.floor}/{prop.total_floors}"
    elif prop.floor:
        floor_info = f"🏢 {prop.floor}-qavat"

    address_line = f"📍 {prop.location_address}\n" if prop.location_address else ""

    area = str(prop.area_sqm) if prop.area_sqm else "—"

    agent = prop.agent
    agent_phone = agent.phone or "—" if agent else "—"
    agent_username = f"@{agent.username}" if agent and agent.username else (agent.full_name if agent else "—")

    features_line = ""
    if prop.features:
        features_line = "✨ " + "  •  ".join(FEATURE_LABELS.get(f, f) for f in prop.features) + "\n\n"

    desc = (prop.description or "")[:500]

    district_tag = "#" + prop.location_district.replace(" ", "_").replace("'", "").replace("'", "")
    rooms_tag = f"#{prop.rooms}xonali"
    price_tag = _price_range_tag(float(prop.price_usd))

    hashtags = f"{district_tag} {rooms_tag} {price_tag}"

    return t(
        "channel_post",
        type_icon=icon,
        prop_type=type_label,
        district=prop.location_district,
        price_usd=f"{int(prop.price_usd):,}",
        price_uzs=price_uzs,
        rooms=prop.rooms,
        floor_info=floor_info,
        area=area,
        address_line=address_line,
        features_line=features_line,
        description=desc,
        agent_phone=agent_phone,
        agent_username=agent_username,
        hashtags=hashtags,
    )


def _price_range_tag(price: float) -> str:
    if price < 30_000:
        return "#narx_0_30K"
    elif price < 60_000:
        return "#narx_30_60K"
    elif price < 100_000:
        return "#narx_60_100K"
    elif price < 200_000:
        return "#narx_100_200K"
    else:
        return "#narx_200K_oshiq"


def truncate(text: str, max_len: int = 500) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"
