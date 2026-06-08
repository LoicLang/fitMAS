from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from fitmas.legacy.domain.memory.fact_memory import normalize_fact_payload

PROFILE_TTLS = {"medium", "long", "permanent"}
WORKING_TTLS = {"immediate", "short"}


def split_memory_payloads(
    payloads: Sequence[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profile_payloads: list[dict[str, Any]] = []
    working_payloads: list[dict[str, Any]] = []

    for payload in payloads:
        normalized = normalize_fact_payload(payload, now=now)
        if normalized.get("ttl") in WORKING_TTLS:
            working_payloads.append(_normalize_working_payload(normalized))
        else:
            profile_payloads.append(normalized)

    return profile_payloads, working_payloads


def _normalize_working_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["scope"] = str(normalized.get("scope") or _derive_scope(normalized))
    return normalized


def _derive_scope(payload: dict[str, Any]) -> str:
    category = str(payload.get("category") or "")
    ttl = str(payload.get("ttl") or "")
    if category in {"execution", "fatigue"}:
        return "day"
    if category in {"availability", "schedule", "constraint"} or ttl == "short":
        return "week"
    return "conversation"
