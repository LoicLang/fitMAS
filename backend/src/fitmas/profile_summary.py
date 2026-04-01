from __future__ import annotations

from typing import Any, Sequence

from fitmas.fact_memory import fact_is_current

_DURABLE_TTLS = {"medium", "long", "permanent"}
_CATEGORY_PRIORITY = {
    "goal": 10,
    "objective": 10,
    "constraint": 9,
    "availability": 8,
    "health": 8,
    "training_state": 7,
    "preference": 6,
    "coaching": 5,
    "pattern": 4,
}
_SKIP_CATEGORIES = {"execution", "calibration_need", "calibration", "fatigue"}


def build_profile_summary(facts: Sequence[Any], *, limit: int = 6) -> str:
    durable = [
        fact
        for fact in facts
        if fact_is_current(fact) and _is_durable(fact) and _category(fact) not in _SKIP_CATEGORIES
    ]
    if not durable:
        return ""

    durable.sort(key=_sort_key, reverse=True)

    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for fact in durable:
        category = _category(fact)
        value = str(_value(fact, "value") or "").strip()
        if not value:
            continue
        dedupe_key = (category, str(_value(fact, "key") or value))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        lines.append(f"- {_label(category)}: {value}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _is_durable(fact: Any) -> bool:
    ttl = str(_value(fact, "ttl") or "").strip().lower()
    return ttl in _DURABLE_TTLS


def _sort_key(fact: Any) -> tuple[float, float, float]:
    category = _category(fact)
    category_score = float(_CATEGORY_PRIORITY.get(category, 1))
    confirmed_score = 1.0 if bool(_value(fact, "confirmed")) else 0.0
    confidence_score = float(_value(fact, "confidence") or 0.0)
    return (category_score, confirmed_score, confidence_score)


def _category(fact: Any) -> str:
    return str(_value(fact, "category") or "").strip().lower()


def _label(category: str) -> str:
    labels = {
        "goal": "objectif",
        "objective": "objectif",
        "constraint": "contrainte",
        "availability": "dispo",
        "health": "sante",
        "training_state": "etat",
        "preference": "preference",
        "coaching": "coach",
        "pattern": "pattern",
    }
    return labels.get(category, category or "memoire")


def _value(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
