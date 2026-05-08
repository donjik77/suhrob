from pathlib import Path

from aiogram.types import FSInputFile


def payment_photo_input(value: str | None):
    if not value:
        return None

    path = Path(value)
    if path.exists() and path.is_file():
        return FSInputFile(path)

    return value
