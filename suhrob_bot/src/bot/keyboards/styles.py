try:
    from aiogram.enums import ButtonStyle

    BTN_SUCCESS = ButtonStyle.SUCCESS
    BTN_DANGER = ButtonStyle.DANGER
    BTN_PRIMARY = ButtonStyle.PRIMARY
except (ImportError, AttributeError):
    BTN_SUCCESS = "success"
    BTN_DANGER = "danger"
    BTN_PRIMARY = "primary"
