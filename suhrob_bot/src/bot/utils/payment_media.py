from pathlib import Path

from aiogram.types import FSInputFile

from src.config import BASE_DIR


def payment_photo_input(value: str | None):
    if not value:
        return None

    path = Path(value)
    if path.exists() and path.is_file():
        return FSInputFile(path)

    media_path = BASE_DIR / "media" / path.name
    if media_path.exists() and media_path.is_file():
        return FSInputFile(media_path)

    return value
