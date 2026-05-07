from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from src.db.models import UserRole
from locales.uz import t


def agent_menu_kb(role: UserRole) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=t("btn_add_property"))
    kb.button(text=t("btn_my_properties"))
    kb.button(text=t("btn_scheduled_posts"))
    kb.button(text=t("btn_stats"))
    kb.button(text=t("btn_settings"))

    if role in (UserRole.director, UserRole.developer):
        kb.button(text=t("btn_agents_management"))
        kb.button(text=t("btn_all_properties"))
        kb.button(text=t("btn_subscription"))
        kb.button(text=t("btn_full_stats"))

    if role == UserRole.developer:
        kb.button(text=t("btn_issue_invoice"))
        kb.button(text=t("btn_confirm_payments"))
        kb.button(text=t("btn_companies"))
        kb.button(text=t("btn_system_settings"))

    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)


def add_district_kb(districts: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in districts:
        builder.button(text=d, callback_data=f"add_prop_district:{d}")
    builder.button(text=t("add_prop_district_new"), callback_data="add_prop_district:__new__")
    builder.button(text=t("back"), callback_data="add_prop_back:type")
    builder.adjust(2)
    return builder.as_markup()


def publish_time_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_publish_now"), callback_data="publish_time:now")
    builder.button(text=t("btn_schedule_post"), callback_data="publish_time:schedule")
    builder.button(text=t("btn_save_only"), callback_data="publish_time:save_only")
    builder.adjust(1)
    return builder.as_markup()


def preview_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("confirm"), callback_data="add_prop_preview:confirm")
    builder.button(text=t("edit"), callback_data="add_prop_preview:edit")
    builder.button(text=t("cancel"), callback_data="add_prop_preview:cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


def my_properties_nav_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    nav_row = []
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
    builder.button(text=t("btn_view"), callback_data=f"prop_action:view:{property_id}")
    builder.button(text=t("btn_edit"), callback_data=f"prop_action:edit:{property_id}")
    builder.button(text=t("btn_delete"), callback_data=f"prop_action:delete:{property_id}")
    builder.button(text=t("btn_change_status"), callback_data=f"prop_action:status:{property_id}")
    builder.button(text=t("btn_republish"), callback_data=f"prop_action:publish:{property_id}")
    builder.button(text=t("back"), callback_data="my_props_page:1")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def property_status_kb(property_id: int) -> InlineKeyboardMarkup:
    from src.db.models import PropertyStatus
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Faol", callback_data=f"prop_setstatus:{property_id}:active")
    builder.button(text="✔️ Sotilgan", callback_data=f"prop_setstatus:{property_id}:sold")
    builder.button(text="🙈 Yashirish", callback_data=f"prop_setstatus:{property_id}:hidden")
    builder.button(text=t("back"), callback_data=f"prop_action:view:{property_id}")
    builder.adjust(3, 1)
    return builder.as_markup()


def delete_confirm_kb(property_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Ha, o'chir", callback_data=f"prop_confirm_delete:{property_id}")
    builder.button(text="❌ Yo'q", callback_data=f"prop_action:view:{property_id}")
    builder.adjust(2)
    return builder.as_markup()
