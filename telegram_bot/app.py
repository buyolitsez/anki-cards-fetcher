from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from ..server.config import ServerSettings
from ..server.repository import Repository
from .handlers import (
    handle_callback,
    handle_help,
    handle_preset,
    handle_start,
    handle_text_message,
    handle_translate_command,
)


def build_application(
    *,
    settings: ServerSettings | None = None,
    repository: Repository | None = None,
) -> Application:
    settings = settings or ServerSettings.from_env()
    repository = repository or Repository(settings.sqlite_path)
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["repository"] = repository
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("tr", handle_translate_command))
    app.add_handler(CommandHandler("preset", handle_preset))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    return app


def quiet_http_loggers() -> None:
    # httpx logs every request URL at INFO, and Telegram API URLs contain the bot token.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    quiet_http_loggers()
    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    main()
