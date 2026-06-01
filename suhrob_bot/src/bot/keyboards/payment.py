from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from locales.uz import t


def payment_method_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_pay_click"), callback_data="pay_method:click")
    builder.button(text=t("btn_pay_humo"), callback_data="pay_method:humo")
    builder.button(text=t("btn_pay_uzcard"), callback_data="pay_method:uzcard")
    builder.button(text=t("btn_pay_crypto"), callback_data="pay_method:crypto")
    builder.button(text=t("cancel"), callback_data="pay_cancel")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def invoice_payment_method_kb(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_pay_click"), callback_data=f"pay_invoice_method:{subscription_id}:click")
    builder.button(text=t("btn_pay_humo"), callback_data=f"pay_invoice_method:{subscription_id}:humo")
    builder.button(text=t("btn_pay_uzcard"), callback_data=f"pay_invoice_method:{subscription_id}:uzcard")
    builder.button(text=t("btn_pay_crypto"), callback_data=f"pay_invoice_method:{subscription_id}:crypto")
    builder.button(text=t("cancel"), callback_data="pay_cancel")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def cancel_payment_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("cancel"), callback_data="pay_cancel")
    return builder.as_markup()


def payment_confirm_kb(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_confirm_payment"), callback_data=f"dev_pay_confirm:{subscription_id}")
    builder.button(text=t("btn_reject_payment"), callback_data=f"dev_pay_reject:{subscription_id}")
    builder.adjust(2)
    return builder.as_markup()


def invoice_amount_kb(default_price: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("invoice_btn_default", price=default_price), callback_data=f"invoice_amount:{default_price}")
    builder.button(text="$99", callback_data="invoice_amount:99")
    builder.button(text=t("invoice_btn_custom"), callback_data="invoice_amount:custom")
    builder.adjust(3)
    return builder.as_markup()


def companies_list_kb(companies: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for company in companies:
        builder.button(
            text=f"{company.name}",
            callback_data=f"invoice_company:{company.id}",
        )
    builder.adjust(1)
    return builder.as_markup()
