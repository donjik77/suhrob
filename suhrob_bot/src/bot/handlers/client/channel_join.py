from aiogram import Router


# Intentionally empty: Telegram bots cannot proactively DM new channel members.
# Use src.bot.templates.channel_welcome for a pinned channel welcome post instead.
router = Router()
