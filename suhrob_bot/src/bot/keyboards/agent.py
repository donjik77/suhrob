from datetime import date, timedelta
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from src.db.models import UserRole
from src.bot.keyboards.styles import BTN_DANGER, BTN_PRIMARY, BTN_SUCCESS
from locales.uz import t

# ─── Feature definitions (used in multi-select step) ─────────────────────────

FEATURES = [
    ("repair",          "🚿 Ta'mirli"),
    ("parking",         "🚗 Avtoturargoh"),
    ("garden",          "🌳 Hovli/Bog'"),
    ("pool",            "🏊 Basseyn"),
    ("ac",              "🌡 Konditsioner"),
    ("furniture",       "🪑 Mebelli"),
    ("elevator",        "🛗 Lift"),
    ("central_heating", "🔥 Markaziy isitish"),
    ("internet",        "🌐 Internet"),
    ("security",        "🛡 Xavfsizlik"),
]

# ─── Main menus ───────────────────────────────────────────────────────────────

def agent_menu_kb(role: UserRole) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=t("btn_add_property"))

    if role in (UserRole.director, UserRole.developer):
        kb.button(text=t("btn_all_properties"))
        kb.button(text=t("btn_all_clients"))
        kb.button(text=t("btn_agents_management"))
        kb.button(text=t("btn_agent_rating"))
        kb.button(text=t("btn_scheduled_posts"))
        kb.button(text=t("btn_full_stats"))
        kb.button(text=t("btn_my_profile"))
        kb.button(text=t("btn_subscription"))
        kb.button(text=t("btn_instagram"))
        kb.button(text=t("btn_settings"))
        kb.button(text=t("btn_help"))
    else:
        kb.button(text=t("btn_my_properties"))
        kb.button(text=t("btn_my_clients"))
        kb.button(text=t("btn_scheduled_posts"))
        kb.button(text=t("btn_stats"))
        kb.button(text=t("btn_shared_profile"))
        kb.button(text=t("btn_instagram"))
        kb.button(text=t("btn_help"))

    if role == UserRole.developer:
        # Developer keeps operational shortcuts after the director menu.
        kb.button(text=t("btn_issue_invoice"))
        kb.button(text=t("btn_confirm_payments"))
        kb.button(text=t("btn_companies"))
        kb.button(text=t("btn_system_settings"))

    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

# ─── Add property — step-by-step FSM keyboards ───────────────────────────────

def property_type_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏢 Kvartira",  callback_data="ap_type:apartment")
    b.button(text="🏡 Hovli",     callback_data="ap_type:house")
    b.button(text="🏪 Tijorat",   callback_data="ap_type:commercial")
    b.adjust(3)
    return b.as_markup()


def district_kb(districts: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in districts:
        builder.button(text=d, callback_data=f"ap_district:{d}")
    builder.button(text="🌍 Boshqa tuman", callback_data="ap_district:__new__")
    builder.adjust(2)
    return builder.as_markup()


def skip_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏭ O'tkazib yuborish", callback_data="ap_skip")
    b.adjust(1)
    return b.as_markup()


def rooms_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in ("1", "2", "3"):
        b.button(text=n, callback_data=f"ap_rooms:{n}")
    for n in ("4", "5+"):
        b.button(text=n, callback_data=f"ap_rooms:{n}")
    b.button(text="Farqi yo'q", callback_data="ap_rooms:any")
    b.adjust(3, 2, 1)
    return b.as_markup()


def area_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for v in ("40", "60", "80", "100", "120", "150+"):
        b.button(text=f"{v} m²", callback_data=f"ap_area:{v}")
    b.button(text="✏️ O'zim", callback_data="ap_area:custom")
    b.button(text="⏭ O'tkazib yuborish", callback_data="ap_area:skip")
    b.adjust(3, 3, 1, 1)
    return b.as_markup()


def price_range_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    ranges = [
        ("$30,000",  "30000"),
        ("$50,000",  "50000"),
        ("$70,000",  "70000"),
        ("$100,000", "100000"),
        ("$150,000", "150000"),
    ]
    for label, val in ranges:
        b.button(text=label, callback_data=f"ap_price:{val}")
    b.button(text="✏️ O'zim", callback_data="ap_price:custom")
    b.adjust(3, 2, 1)
    return b.as_markup()


def features_kb(selected: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, label in FEATURES:
        prefix = "✅ " if key in selected else ""
        b.button(text=f"{prefix}{label}", callback_data=f"ap_feat:{key}")
    b.button(text="Tayyor", callback_data="ap_feat:done")
    b.adjust(2, 2, 2, 2, 2, 1)
    return b.as_markup()


def media_done_kb(photo_count: int, video_count: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if photo_count or video_count:
        parts = []
        if photo_count:
            parts.append(f"{photo_count} ta rasm")
        if video_count:
            parts.append(f"{video_count} ta video")
        b.button(text=f"Tayyor ({', '.join(parts)})", callback_data="ap_media:done")
    b.adjust(1)
    return b.as_markup()


def preview_action_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Hammasi yaxshi",      callback_data="ap_preview:confirm", style=BTN_SUCCESS)
    b.button(text="✏️ Matnni o'zgartirish",    callback_data="ap_preview:edit_text", style=BTN_PRIMARY)
    b.button(text="🤖 AI dan boshqa variant",  callback_data="ap_preview:regen", style=BTN_PRIMARY)
    b.button(text="❌ Bekor qilish",         callback_data="ap_preview:cancel", style=BTN_DANGER)
    b.adjust(1)
    return b.as_markup()


def publish_options_kb(property_id: int | None = None) -> InlineKeyboardMarkup:
    suffix = f":{property_id}" if property_id is not None else ""
    b = InlineKeyboardBuilder()
    b.button(text="📢 Hozir publikatsiya",       callback_data=f"ap_pub:now{suffix}", style=BTN_SUCCESS)
    b.button(text="⏰ Keyinchalik rejalashtirish", callback_data=f"ap_pub:schedule{suffix}", style=BTN_PRIMARY)
    b.button(text="💾 Faqat bazaga saqlash",      callback_data=f"ap_pub:save_only{suffix}", style=BTN_SUCCESS)
    b.adjust(1)
    return b.as_markup()


def publish_date_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    today = date.today()
    for delta, label in [(1, "Ertaga"), (2, "2 kundan keyin"), (3, "3 kundan keyin")]:
        d = today + timedelta(days=delta)
        b.button(text=f"📅 {label} ({d.strftime('%d.%m')})", callback_data=f"ap_date:{d.isoformat()}")
    b.button(text="✏️ O'z sanani kiriting", callback_data="ap_date:custom")
    b.adjust(1)
    return b.as_markup()


def publish_time_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for tm in ("09:00", "12:00", "15:00", "18:00", "21:00"):
        b.button(text=f"🕐 {tm}", callback_data=f"ap_time:{tm}")
    b.button(text="✏️ O'z vaqtni kiriting", callback_data="ap_time:custom")
    b.adjust(3, 2, 1)
    return b.as_markup()

# ─── Existing keyboards kept for backward compatibility ───────────────────────

def type_select_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏢 Kvartira", callback_data="add_prop_type:apartment")
    b.button(text="🏡 Hovli",    callback_data="add_prop_type:house")
    b.button(text="🏪 Tijorat",  callback_data="add_prop_type:commercial")
    b.adjust(3)
    return b.as_markup()


def parsed_preview_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Tur",      callback_data="edit_field:property_type")
    b.button(text="✏️ Tuman",    callback_data="edit_field:district")
    b.button(text="✏️ Manzil",   callback_data="edit_field:address")
    b.button(text="✏️ Xonalar",  callback_data="edit_field:rooms")
    b.button(text="✏️ Qavat",    callback_data="edit_field:floor")
    b.button(text="✏️ Maydon",   callback_data="edit_field:area_sqm")
    b.button(text="✏️ Narx",     callback_data="edit_field:price_usd")
    b.button(text="✏️ Tavsif",   callback_data="edit_field:description")
    b.button(text="✅ Tasdiqlash", callback_data="parsed_confirm", style=BTN_SUCCESS)
    b.button(text="❌ Bekor qilish", callback_data="parsed_cancel", style=BTN_DANGER)
    b.adjust(2, 2, 2, 2, 1, 1)
    return b.as_markup()


def add_district_kb(districts: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in districts:
        builder.button(text=d, callback_data=f"add_prop_district:{d}")
    builder.button(text=t("add_prop_district_new"), callback_data="add_prop_district:__new__")
    builder.adjust(2)
    return builder.as_markup()


def my_properties_nav_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.button(text="⬅️", callback_data=f"my_props_page:{page - 1}")
    builder.button(text=f"Sahifa {page}/{total_pages}", callback_data="noop")
    if page < total_pages:
        builder.button(text="➡️", callback_data=f"my_props_page:{page + 1}")
    builder.button(text="🔍 Filtr", callback_data="my_props_filter")
    builder.adjust(3, 1)
    return builder.as_markup()


def property_actions_kb(property_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_view"),          callback_data=f"prop_action:view:{property_id}", style=BTN_PRIMARY)
    builder.button(text=t("btn_edit"),          callback_data=f"prop_action:edit:{property_id}", style=BTN_PRIMARY)
    builder.button(text=t("btn_delete"),        callback_data=f"prop_action:delete:{property_id}", style=BTN_DANGER)
    builder.button(text=t("btn_change_status"), callback_data=f"prop_action:status:{property_id}", style=BTN_PRIMARY)
    builder.button(text=t("btn_republish"),     callback_data=f"prop_action:publish:{property_id}", style=BTN_SUCCESS)
    builder.button(text=t("back"),              callback_data="my_props_page:1", style=BTN_PRIMARY)
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def property_status_kb(property_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Faol",       callback_data=f"prop_setstatus:{property_id}:active", style=BTN_SUCCESS)
    builder.button(text="✔️ Sotilgan",  callback_data=f"prop_setstatus:{property_id}:sold", style=BTN_SUCCESS)
    builder.button(text="🙈 Yashirish", callback_data=f"prop_setstatus:{property_id}:hidden", style=BTN_DANGER)
    builder.button(text=t("back"),      callback_data=f"prop_action:view:{property_id}", style=BTN_PRIMARY)
    builder.adjust(3, 1)
    return builder.as_markup()


def delete_confirm_kb(property_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ha, o'chir", callback_data=f"prop_confirm_delete:{property_id}", style=BTN_DANGER)
    builder.button(text="❌ Yo'q",       callback_data=f"prop_action:view:{property_id}", style=BTN_PRIMARY)
    builder.adjust(2)
    return builder.as_markup()


def edit_property_fields_kb(property_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fields = [
        ("🏠 Tur",         "property_type"),
        ("📍 Tuman",       "location_district"),
        ("🏠 Manzil",      "location_address"),
        ("🚪 Xonalar",     "rooms"),
        ("🏢 Qavat",       "floor"),
        ("🏢 Jami qavat",  "total_floors"),
        ("📐 Maydon",      "area_sqm"),
        ("💰 Narx",        "price_usd"),
        ("📝 Tavsif",      "description"),
    ]
    for label, field in fields:
        builder.button(text=label, callback_data=f"edit_prop_field:{property_id}:{field}")
    builder.button(text="✅ Tayyor", callback_data=f"prop_action:view:{property_id}", style=BTN_SUCCESS)
    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def type_select_existing_kb(property_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏢 Kvartira", callback_data=f"edit_prop_type:{property_id}:apartment")
    b.button(text="🏡 Hovli",   callback_data=f"edit_prop_type:{property_id}:house")
    b.button(text="🏪 Tijorat", callback_data=f"edit_prop_type:{property_id}:commercial")
    b.adjust(3)
    return b.as_markup()
