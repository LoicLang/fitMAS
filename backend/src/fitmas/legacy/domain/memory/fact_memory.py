from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

TTL_WINDOWS = {
    "immediate": timedelta(hours=18),
    "short": timedelta(days=3),
    "medium": timedelta(days=21),
    "long": timedelta(days=180),
    "permanent": None,
}

CATEGORY_AFFECTS = {
    "availability": ("planning", "conversation", "heartbeat", "readiness"),
    "schedule": ("planning", "conversation", "heartbeat", "readiness"),
    "constraint": ("planning", "conversation", "heartbeat"),
    "health": ("planning", "conversation", "heartbeat", "readiness"),
    "fatigue": ("planning", "conversation", "heartbeat", "readiness"),
    "calibration_need": ("conversation", "heartbeat"),
    "goal": ("planning", "conversation"),
    "objective": ("planning", "conversation"),
    "training_state": ("planning", "conversation", "heartbeat"),
    "pattern": ("planning", "conversation"),
    "preference": ("planning", "conversation"),
    "coaching": ("conversation",),
    "execution": ("conversation", "heartbeat"),
}

INACTIVE_STATUSES = {"resolved", "superseded", "stale", "archived", "closed"}


@dataclass(frozen=True, slots=True)
class FactMemoryPolicy:
    urgency: str
    ttl: str
    affects: tuple[str, ...]
    expires_at: datetime | None


def derive_fact_memory_policy(
    *,
    category: str,
    value: str,
    source: str,
    now: datetime | None = None,
) -> FactMemoryPolicy:
    normalized_category = (category or "").strip().lower() or "preference"
    affects = CATEGORY_AFFECTS.get(normalized_category, ("conversation",))

    ttl = "medium"
    urgency = "medium"

    if normalized_category in {"coaching", "preference"}:
        ttl = "long"
        urgency = "low"
    elif normalized_category in {"goal", "objective", "pattern"}:
        ttl = "long"
        urgency = "medium"
    elif normalized_category == "training_state":
        ttl = "medium"
        urgency = "medium"
    elif normalized_category in {"availability", "schedule", "constraint"}:
        ttl = "medium"
        urgency = "medium"
    elif normalized_category == "execution":
        ttl = "immediate"    # 18h — activity claim, same-day only
        urgency = "high"
    elif normalized_category == "fatigue":
        ttl = "immediate"    # 18h — fatigue is a signal of the day, not 3 days
        urgency = "high"
    elif normalized_category == "health":
        ttl = "medium"
        urgency = "high"

    if source == "onboarding" and normalized_category in {"goal", "objective", "coaching", "preference"}:
        ttl = "permanent"

    expires_at = _compute_expires_at(ttl, now=now)
    return FactMemoryPolicy(
        urgency=urgency,
        ttl=ttl,
        affects=tuple(affects),
        expires_at=expires_at,
    )


def normalize_fact_payload(fact: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    normalized = dict(fact)
    explicit_ttl = bool(str(normalized.get("ttl") or "").strip())
    policy = derive_fact_memory_policy(
        category=str(normalized.get("category", "")),
        value=str(normalized.get("value", "")),
        source=str(normalized.get("source", "conversation")),
        now=now,
    )
    normalized["urgency"] = str(normalized.get("urgency") or policy.urgency)
    normalized["ttl"] = str(normalized.get("ttl") or policy.ttl)
    affects = normalized.get("affects")
    if not isinstance(affects, list) or not affects:
        affects = list(policy.affects)
    normalized["affects"] = [str(value) for value in affects]
    normalized["expires_at"] = _coerce_datetime(normalized.get("expires_at")) or policy.expires_at
    normalized["active"] = bool(normalized.get("active", True))
    status = str(normalized.get("status") or "open").strip().lower()
    normalized["status"] = status if status else "open"
    normalized["severity"] = str(normalized.get("severity") or normalized.get("urgency") or "medium").strip().lower()
    signal_kind = str(normalized.get("signal_kind") or "").strip().lower()
    if signal_kind:
        normalized["signal_kind"] = signal_kind
    if not explicit_ttl and str(normalized.get("category") or "").strip().lower() == "health":
        if normalized["severity"] == "mild" and signal_kind in {"tension", "fatigue", "sleep", "illness", "other", ""}:
            normalized["ttl"] = "short"
            normalized["expires_at"] = _compute_expires_at("short", now=now)
    observed_at = _coerce_datetime(normalized.get("observed_at")) or _utc_now(now=now)
    normalized["observed_at"] = observed_at
    normalized["valid_from"] = _coerce_datetime(normalized.get("valid_from")) or observed_at
    normalized["valid_until"] = _coerce_datetime(normalized.get("valid_until")) or normalized["expires_at"]
    normalized["last_seen_at"] = _coerce_datetime(normalized.get("last_seen_at")) or observed_at
    normalized["resolved_at"] = _coerce_datetime(normalized.get("resolved_at"))
    normalized["resolution_reason"] = str(normalized.get("resolution_reason") or "")
    return normalized


def fact_is_current(fact: Any, *, now: datetime | None = None) -> bool:
    if _value(fact, "active") is False:
        return False
    current = _utc_now(now=now)
    status = str(_value(fact, "status") or "open").strip().lower()
    if status in INACTIVE_STATUSES:
        return False
    valid_from = _coerce_datetime(_value(fact, "valid_from"))
    if valid_from is not None and _as_utc(valid_from) > current:
        return False
    valid_until = _coerce_datetime(_value(fact, "valid_until"))
    expires_at = _coerce_datetime(_value(fact, "expires_at"))
    end_at = valid_until or expires_at
    if end_at is None:
        return True
    return _as_utc(end_at) >= current


def select_relevant_facts(
    facts: Sequence[Any],
    *,
    affects: Sequence[str] | None = None,
    limit: int = 6,
    now: datetime | None = None,
) -> list[str]:
    active = [fact for fact in facts if fact_is_current(fact, now=now)]
    if not active:
        return []

    preferred = set(affects or [])
    active.sort(key=lambda fact: _fact_sort_key(fact, preferred_affects=preferred), reverse=True)

    selected: list[str] = []
    seen: set[tuple[str, str]] = set()
    for fact in active:
        if str(_value(fact, "category") or "") in {"calibration_need", "calibration"}:
            continue
        key = (str(_value(fact, "category") or ""), str(_value(fact, "key") or ""))
        if key in seen:
            continue
        seen.add(key)
        selected.append(f"[{_value(fact, 'category')}] {_value(fact, 'value')}")
        if len(selected) >= limit:
            break
    return selected


def select_readiness_facts(
    facts: Sequence[Any],
    *,
    limit: int = 12,
    now: datetime | None = None,
) -> list[Any]:
    selected = [
        fact
        for fact in facts
        if fact_is_current(fact, now=now)
        and "readiness" in _coerce_affects(_value(fact, "affects") or _value(fact, "affects_json"))
    ]
    selected.sort(key=lambda fact: _fact_sort_key(fact, preferred_affects={"readiness"}), reverse=True)
    return selected[:limit]


def _fact_sort_key(fact: Any, *, preferred_affects: set[str]) -> tuple[float, float, float, float]:
    urgency_score = {"high": 3.0, "medium": 2.0, "low": 1.0}.get(str(_value(fact, "urgency") or "medium"), 1.0)
    confirmed_score = 1.0 if bool(_value(fact, "confirmed")) else 0.0
    confidence_score = float(_value(fact, "confidence") or 0.0)
    affects = _coerce_affects(_value(fact, "affects") or _value(fact, "affects_json"))
    affect_score = 1.0 if preferred_affects and preferred_affects.intersection(affects) else 0.0
    return (confirmed_score, affect_score, urgency_score, confidence_score)


def _compute_expires_at(ttl: str, *, now: datetime | None = None) -> datetime | None:
    window = TTL_WINDOWS.get(ttl)
    if window is None:
        return None
    current = _utc_now(now=now)
    return (current + window).replace(tzinfo=None)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _coerce_affects(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                import json

                data = json.loads(stripped)
                return {str(item) for item in data}
            except Exception:
                return set()
    return set()


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _utc_now(*, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)
