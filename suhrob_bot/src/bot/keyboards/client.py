from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from locales.uz import t
from src.bot.keyboards.styles import BTN_SUCCESS, BTN_PRIMARY, BTN_DANGER


def request_client_phone_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="Telefon raqamni yuborish", request_contact=True)
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)


def main_menu_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text=t("btn_search"))
    kb.button(text=t("btn_favorites"))
    kb.button(text=t("btn_consultation"))
    kb.button(text=t("btn_notifications"))
    kb.button(text=t("btn_contact"))
    kb.button(text=t("btn_help"))
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)


def search_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("type_apartment"), callback_data="search_type:apartment")
    builder.button(text=t("type_house"), callback_data="search_type:house")
    builder.button(text=t("type_commercial"), callback_data="search_type:commercial")
    builder.button(text=t("back"), callback_data="search_back:start")
    builder.adjust(3, 1)
    return builder.as_markup()


def search_district_kb(districts: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in districts:
        builder.button(text=d, callback_data=f"search_district:{d}")
    builder.button(text=t("district_other"), callback_data="search_district:__other__")
    builder.button(text=t("back"), callback_data="search_back:type")
    builder.adjust(2)
    return builder.as_markup()


def search_rooms_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in [1, 2, 3, 4, 5]:
        builder.button(text=str(r), callback_data=f"search_rooms:{r}")
    builder.button(text="5+", callback_data="search_rooms:5+")
    builder.button(text=t("rooms_any"), callback_data="search_rooms:any")
    builder.button(text=t("back"), callback_data="search_back:district")
    builder.adjust(3, 2, 1, 1)
    return builder.as_markup()


def search_price_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    ranges = [
        ("$0 - $30,000", "0:30000"),
        ("$30,000 - $60,000", "30000:60000"),
        ("$60,000 - $100,000", "60000:100000"),
        ("$100,000 - $200,000", "100000:200000"),
        ("$200,000+", "200000:"),
    ]
    for label, val in ranges:
        builder.button(text=label, callback_data=f"search_price:{val}")
    builder.button(text=t("price_custom"), callback_data="search_price:custom")
    builder.button(text=t("back"), callback_data="search_back:rooms")
    builder.adjust(1)
    return builder.as_markup()


def property_card_kb(property_id: int, is_favorite: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=t("btn_contact_agent"),
        callback_data=f"prop_contact:{property_id}",
        style=BTN_SUCCESS,
    ))
    if is_favorite:
        builder.add(InlineKeyboardButton(
            text=t("btn_remove_favorite"),
            callback_data=f"prop_unfav:{property_id}",
            style=BTN_DANGER,
        ))
    else:
        builder.add(InlineKeyboardButton(
            text=t("btn_save_property"),
            callback_data=f"prop_fav:{property_id}",
            style=BTN_PRIMARY,
        ))
    builder.add(InlineKeyboardButton(
        text=t("btn_ai_ask"),
        callback_data=f"ai_consult:{property_id}",
        style=BTN_PRIMARY,
    ))
    builder.add(InlineKeyboardButton(
        text=t("btn_mortgage"),
        callback_data=f"mortgage:{property_id}",
    ))
    builder.add(InlineKeyboardButton(
        text=t("btn_share"),
        switch_inline_query=f"property_{property_id}",
    ))
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def search_results_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_new_search"), callback_data="search_new")
    builder.button(text=t("btn_save_all"), callback_data="search_save_all")
    builder.adjust(1)
    return builder.as_markup()


def no_results_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_other_params"), callback_data="search_new")
    builder.button(text=t("btn_notify_new"), callback_data="search_notify")
    builder.adjust(1)
    return builder.as_markup()


def favorites_kb(property_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text=t("btn_remove_favorite"),
        callback_data=f"prop_unfav:{property_id}",
        style=BTN_DANGER,
    ))
    builder.add(InlineKeyboardButton(
        text=t("btn_contact_agent"),
        callback_data=f"prop_contact:{property_id}",
        style=BTN_SUCCESS,
    ))
    builder.adjust(2)
    return builder.as_markup()
