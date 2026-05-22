from __future__ import annotations

import json
import logging
from typing import Any


logger = logging.getLogger(__name__)


def decision_json_for_turn(decision: Any | None) -> str:
    if decision is None:
        return "{}"
    try:
        if hasattr(decision, "model_dump_json"):
            return str(decision.model_dump_json())
        if hasattr(decision, "model_dump"):
            return json.dumps(decision.model_dump(mode="json"), ensure_ascii=True, default=str)
        if isinstance(decision, dict):
            return json.dumps(decision, ensure_ascii=True, default=str)
    except Exception:
        logger.exception("conversation_decision_json_serialization_failed")
    return "{}"


def decision_reply_text_for_turn(decision: Any | None) -> str:
    if decision is None:
        return ""
    for attribute in ("reply_hint", "fitmas_message", "rationale"):
        text = str(getattr(decision, attribute, "") or "").strip()
        if text:
            return text
    return ""
