from __future__ import annotations

import logging
import os

import httpx
from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.domain.athlete import repository as athlete_repo

logger = logging.getLogger(__name__)


def resolve_chat_id(db: Session, *, user: s.User | None = None) -> int | None:
    explicit = os.getenv("TELEGRAM_CHAT_ID")
    if explicit:
        try:
            return int(explicit)
        except ValueError:
            logger.warning("Invalid TELEGRAM_CHAT_ID env value: %s", explicit)

    resolved_user = user or athlete_repo.get_user_optional(db)
    if resolved_user and resolved_user.telegram_chat_id:
        return int(resolved_user.telegram_chat_id)
    return None


def send_text_message(*, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return False

    response = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return bool(payload.get("ok"))
