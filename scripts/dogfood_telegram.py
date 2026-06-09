"""Standalone V0 Telegram dogfood runner.

Polls Telegram, routes an allowlisted user's message to runtime_v0.handle_event
on the V0's own v0_* SQLite store, and sends the coach reply back.

Makes the proven V0 week loop (propose week -> confirm -> adjust under injury)
dogfoodable from Telegram, locally, no deploy, no legacy DB.

Launch:
    set -a && . ./.env && set +a
    export FITMAS_V0_DOGFOOD_CHAT_IDS="<your telegram chat id>"
    .venv/bin/python scripts/dogfood_telegram.py

Env vars:
    FITMAS_V0_DOGFOOD_CHAT_IDS   comma-separated chat ids (required)
    FITMAS_V0_BOT_TOKEN          Telegram bot token (or TELEGRAM_BOT_TOKEN)
    FITMAS_V0_DOGFOOD_PROVIDER   LLM provider (default: deepseek)
    FITMAS_V0_DB_PATH            SQLite path (default: fitmas_v0.db)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

# ---------------------------------------------------------------------------
# sys.path bootstrap — mirror probe pattern (this file is in scripts/, one
# level shallower than scripts/v0_eval/, so parents[1] is repo root)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "backend" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dotenv import load_dotenv  # noqa: E402

from fitmas.runtime_v0.db import db_path_from_env, init_db  # noqa: E402
from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event  # noqa: E402

from scripts.v0_eval.provider_clients import (  # noqa: E402
    ProviderConfigError,
    build_provider_client,
)

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set up logging — and keep the bot token out of the logs.

    httpx/httpcore log every request at INFO, and the Telegram bot token sits in
    the request URL path (``/bot<TOKEN>/...``). Left at INFO that token lands in
    the Fly logs on every poll. Pin those loggers to WARNING; keep ours at INFO.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Deps builder — mirrors probe _build_deps, no MeteredLLMClient
# ---------------------------------------------------------------------------

def build_deps(provider: str = "deepseek", db_path: Path | None = None) -> RuntimeDeps:
    """Build RuntimeDeps for the given provider.

    Raises ProviderConfigError if credentials are missing.
    coach max_tokens=1024, generation=4096, reply=4096 (same budget as probes).
    """
    if db_path is None:
        db_path = db_path_from_env()

    coach_llm = build_provider_client(provider, max_tokens=1024)
    generation_llm = build_provider_client(provider, max_tokens=4096)
    reply_llm = build_provider_client(provider, max_tokens=4096)

    return RuntimeDeps(
        db_path=db_path,
        coach_llm=coach_llm,
        generation_llm=generation_llm,
        reply_llm=reply_llm,
        max_steps=6,
    )


# ---------------------------------------------------------------------------
# Core message handler — pure of Telegram objects, smoke-testable offline
# ---------------------------------------------------------------------------

def handle_message_text(
    deps: RuntimeDeps,
    chat_id: int,
    message_id: int,
    text: str,
    now: datetime,
) -> str:
    """Run one V0 turn for the given message. Returns the coach reply (may be empty)."""
    event = InputEvent(
        id=f"tg-{chat_id}-{message_id}",
        user_id=chat_id,
        source="telegram",
        type="user_message",
        text=text,
        payload={},
        occurred_at=now,
    )
    result = handle_event(event, deps, turn_id=event.id)
    return result.reply or ""


# ---------------------------------------------------------------------------
# Telegram wiring
# ---------------------------------------------------------------------------

def _parse_allowlist(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                logger.warning("dogfood: ignoring non-integer chat id %r", part)
    return ids


def main() -> None:
    _configure_logging()

    # Load .env so credentials are available without manual export
    load_dotenv(ROOT / ".env")

    # --- Config from env ---
    raw_ids = os.getenv("FITMAS_V0_DOGFOOD_CHAT_IDS", "")
    allowlist = _parse_allowlist(raw_ids)
    if not allowlist:
        logger.warning(
            "dogfood: FITMAS_V0_DOGFOOD_CHAT_IDS is empty — "
            "all messages will be refused. Set it to your Telegram chat id."
        )

    token = os.getenv("FITMAS_V0_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "Missing Telegram token. Set FITMAS_V0_BOT_TOKEN or TELEGRAM_BOT_TOKEN."
        )

    provider = os.getenv("FITMAS_V0_DOGFOOD_PROVIDER", "deepseek")

    # --- DB init (idempotent) ---
    db_path = db_path_from_env()
    init_db(db_path)
    logger.info("dogfood: db=%s provider=%s allowlist=%s", db_path, provider, allowlist)

    # --- Build deps once at startup ---
    try:
        deps = build_deps(provider=provider, db_path=db_path)
    except ProviderConfigError as exc:
        raise SystemExit(f"Provider config error: {exc}") from exc

    # --- Telegram app ---
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters

    async def on_message(update: object, context: object) -> None:  # noqa: ARG001
        from telegram import Update as TGUpdate

        upd: TGUpdate = update  # type: ignore[assignment]
        msg = upd.effective_message
        chat = upd.effective_chat
        if msg is None or chat is None:
            return

        chat_id: int = chat.id
        message_id: int = msg.message_id
        text: str = msg.text or ""

        if chat_id not in allowlist:
            await msg.reply_text("Accès dogfood non autorisé.")
            return

        t0 = monotonic()
        try:
            now = datetime.now(timezone.utc)
            reply = await asyncio.get_running_loop().run_in_executor(
                None, handle_message_text, deps, chat_id, message_id, text, now
            )
        except Exception:
            logger.exception("dogfood: turn error chat_id=%s msg_id=%s", chat_id, message_id)
            await msg.reply_text("Souci technique, réessaie.")
            return

        latency_ms = int((monotonic() - t0) * 1000)
        logger.info(
            "dogfood: provider=%s chat_id=%s latency_ms=%d reply_len=%d",
            provider, chat_id, latency_ms, len(reply),
        )

        if reply.strip():
            await msg.reply_text(reply)

    tg_app = Application.builder().token(token).build()
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Periodic Strava -> V0 sync: pull the user's real runs into the V0 store so the
    # coach knows what they actually trained. Lazy import (the legacy bridge) so a
    # legacy import problem can never block the conversational bot.
    legacy_db_path = Path(os.getenv("FITMAS_DB_PATH", "fitmas.db"))
    legacy_user_id = int(os.getenv("FITMAS_V0_STRAVA_LEGACY_USER", "1"))
    strava_interval = int(os.getenv("FITMAS_V0_STRAVA_SYNC_SECONDS", "900"))

    # Strava sync is solo: one legacy account (legacy_user_id) maps to ONE runner.
    # Applying it to every allowlisted chat would pull the same person's runs into
    # someone else's store, so only sync the owner chat (the first allowlisted id).
    # Per-user Strava mapping is a multi-user concern, deliberately not built yet.
    strava_chat_ids = allowlist[:1]
    if len(allowlist) > 1:
        logger.warning(
            "dogfood: strava->v0 sync is solo (legacy user %s) — syncing only chat %s and "
            "skipping %d other allowlisted chat(s); per-user Strava mapping is not built yet",
            legacy_user_id, strava_chat_ids[0], len(allowlist) - 1,
        )

    async def _strava_sync_job(context: object) -> None:  # noqa: ARG001
        from functools import partial
        try:
            from fitmas.runtime_v0.adapters.strava_v0_sync import sync_strava_to_v0
        except Exception:
            logger.exception("dogfood: strava sync adapter import failed")
            return
        loop = asyncio.get_running_loop()
        for uid in strava_chat_ids:
            try:
                n = await loop.run_in_executor(
                    None,
                    partial(
                        sync_strava_to_v0,
                        legacy_db_path=legacy_db_path,
                        v0_db_path=db_path,
                        legacy_user_id=legacy_user_id,
                        runner_user_id=uid,
                    ),
                )
                if n:
                    logger.info("dogfood: strava->v0 synced %d new activities (chat %s)", n, uid)
            except Exception:
                logger.exception("dogfood: strava->v0 sync failed (chat %s)", uid)

    if strava_chat_ids and tg_app.job_queue is not None:
        tg_app.job_queue.run_repeating(_strava_sync_job, interval=strava_interval, first=15, name="strava_v0_sync")
        logger.info("dogfood: strava->v0 sync every %ds (chat %s)", strava_interval, strava_chat_ids[0])

    logger.info("dogfood: starting polling...")
    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
