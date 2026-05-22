"""FitMAS Telegram bot — bridges Telegram to the FastAPI backend."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, PicklePersistence

load_dotenv(Path(__file__).resolve().parents[5] / ".env")

from fitmas.app.telegram.commands import register_command_handlers
from fitmas.app.telegram.onboarding import build_onboarding_handler
from fitmas.app.telegram.scheduler import register_jobs

logger = logging.getLogger(__name__)


def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set in environment")

    db_path = os.getenv("FITMAS_DB_PATH", "fitmas.db")
    persistence_path = str(Path(db_path).parent / "telegram_persistence.pickle")
    persistence = PicklePersistence(filepath=persistence_path)
    app = Application.builder().token(token).persistence(persistence).build()

    app.add_handler(build_onboarding_handler())
    register_command_handlers(app)
    register_jobs(app)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = build_application()
    logger.info("FitMAS Telegram bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
