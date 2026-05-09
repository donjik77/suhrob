from dataclasses import dataclass

from src.config import settings
from src.db.repositories.settings_repo import SettingsRepository


@dataclass
class CardPaymentDetails:
    card: str | None
    holder: str | None
    qr_file_id: str | None


@dataclass
class CryptoPaymentDetails:
    address: str | None
    network: str | None


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _config_value(name: str) -> str | None:
    return _clean(getattr(settings, name, None))


async def get_card_payment_details(
    settings_repo: SettingsRepository,
    method: str,
) -> CardPaymentDetails:
    env_prefix = f"PAYMENT_{method.upper()}"
    db_prefix = f"payment_{method}"
    card = _config_value(f"{env_prefix}_CARD") or await settings_repo.get(f"{db_prefix}_card")
    holder = _config_value(f"{env_prefix}_HOLDER") or await settings_repo.get(f"{db_prefix}_holder")
    qr_file_id = (
        _config_value(f"{env_prefix}_QR_FILE_ID")
        or await settings_repo.get(f"{db_prefix}_qr_file_id")
        or await settings_repo.get(f"{db_prefix}_qr_photo")
        or _config_value("PAYMENT_CARD_QR_FILE_ID")
        or await settings_repo.get("payment_card_qr_file_id")
        or await settings_repo.get("payment_card_qr_photo")
    )
    return CardPaymentDetails(card=card, holder=holder, qr_file_id=qr_file_id)


async def get_crypto_payment_details(
    settings_repo: SettingsRepository,
) -> CryptoPaymentDetails:
    address = _config_value("PAYMENT_CRYPTO_ADDRESS") or await settings_repo.get("payment_crypto_address")
    network = _config_value("PAYMENT_CRYPTO_NETWORK") or await settings_repo.get("payment_crypto_network")
    return CryptoPaymentDetails(address=address, network=network)
