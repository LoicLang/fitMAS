from __future__ import annotations

from typing import Any, Literal

FallbackOwner = Literal[
    "planning",
    "pending",
    "command",
    "reply",
    "readonly",
    "legacy_provider",
    "clarification",
    "integration",
]

_OWNERS = {
    "planning",
    "pending",
    "command",
    "reply",
    "readonly",
    "legacy_provider",
    "clarification",
    "integration",
}
_SEVERITIES = {"expected", "needs_migration", "blocked", "error"}
_UNCLASSIFIED_LEGACY_REASON = "legacy fallback used without fallback census"


def record_fallback(
    turn_context: dict[str, object],
    *,
    owner: FallbackOwner | str,
    source: str,
    reason: str,
    legacy_path: str | None = None,
    next_step: str | None = None,
    severity: str = "needs_migration",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_owner = str(owner or "").strip()
    clean_source = str(source or "").strip()
    clean_reason = str(reason or "").strip()
    clean_severity = str(severity or "").strip()
    if clean_owner not in _OWNERS:
        raise ValueError(f"unknown fallback owner: {clean_owner!r}")
    if not clean_source:
        raise ValueError("fallback source is required")
    if not clean_reason:
        raise ValueError("fallback reason is required")
    if clean_severity not in _SEVERITIES:
        raise ValueError(f"unknown fallback severity: {clean_severity!r}")

    entry: dict[str, Any] = {
        "owner": clean_owner,
        "source": clean_source,
        "reason": clean_reason,
        "legacy_path": str(legacy_path or "").strip() or None,
        "next_step": str(next_step or "").strip() or None,
        "severity": clean_severity,
        "metadata": dict(metadata or {}),
    }
    entries = _mutable_entries(turn_context)
    if entry not in entries:
        entries.append(entry)
    return entry


def record_legacy_provider_fallback(
    turn_context: dict[str, object],
    *,
    response_type: str | None = None,
    ok: bool | None = None,
) -> dict[str, Any]:
    owner, source, reason, next_step = _classify_legacy_provider_fallback(turn_context)
    metadata: dict[str, Any] = {}
    if response_type:
        metadata["response_type"] = response_type
    if ok is not None:
        metadata["ok"] = bool(ok)
    return record_fallback(
        turn_context,
        owner=owner,
        source=source,
        reason=reason,
        legacy_path="CoachDecision",
        next_step=next_step,
        severity="needs_migration",
        metadata=metadata,
    )


def fallback_entries(turn_context: dict[str, object]) -> tuple[dict[str, Any], ...]:
    raw_entries = turn_context.get("fallback_census")
    if not isinstance(raw_entries, (list, tuple)):
        return ()
    return tuple(entry for entry in raw_entries if isinstance(entry, dict))


def unclassified_legacy_fallback_reasons(turn_context: dict[str, object]) -> tuple[str, ...]:
    legacy = turn_context.get("legacy_decide")
    if not isinstance(legacy, dict):
        return ()
    if legacy.get("legacy_skipped") is True:
        return ()
    if any(_is_active_legacy_entry(entry) for entry in fallback_entries(turn_context)):
        return ()
    return (_UNCLASSIFIED_LEGACY_REASON,)


def _mutable_entries(turn_context: dict[str, object]) -> list[dict[str, Any]]:
    raw_entries = turn_context.get("fallback_census")
    if isinstance(raw_entries, list):
        return raw_entries
    entries = [entry for entry in fallback_entries(turn_context)]
    turn_context["fallback_census"] = entries
    return entries


def _classify_legacy_provider_fallback(
    turn_context: dict[str, object],
) -> tuple[FallbackOwner, str, str, str]:
    planning = turn_context.get("canonical_planning_provider")
    if isinstance(planning, dict) and str(planning.get("result") or "") == "fallback_legacy":
        return (
            "planning",
            "canonical_planning_provider",
            _reason(planning, default="fallback_legacy"),
            "migrate requested_change coverage or return a canonical clarification/block outcome",
        )

    pending = turn_context.get("canonical_pending_provider")
    if isinstance(pending, dict) and str(pending.get("result") or "") in {
        "fallback_legacy",
        "no_pending_resolution",
    }:
        return (
            "pending",
            "canonical_pending_provider",
            _reason(pending, default=str(pending.get("result") or "fallback_legacy")),
            "migrate pending resolution coverage to canonical pending outcomes",
        )

    readonly = turn_context.get("canonical_readonly_reply")
    if isinstance(readonly, dict) and readonly.get("composed") is False:
        return (
            "reply",
            "canonical_readonly_reply",
            _reason(readonly, default="compose_failed"),
            "make ReplyComposer produce a canonical answer or return a clarification",
        )

    understanding = turn_context.get("canonical_understanding")
    if isinstance(understanding, dict):
        intent = str(understanding.get("intent") or "").strip()
        if intent:
            return (
                "legacy_provider",
                "legacy_decide",
                f"canonical_understanding_unconsumed:{intent}",
                "route this intent to a canonical outcome or mark it unsupported explicitly",
            )

    return (
        "legacy_provider",
        "legacy_decide",
        "canonical_not_prepared",
        "prepare or intentionally bypass canonical Understanding for this lane",
    )


def _reason(trace: dict[str, Any], *, default: str) -> str:
    for key in ("fallback_reason", "reason", "attempt_reason", "result"):
        value = str(trace.get(key) or "").strip()
        if value:
            return value
    return default


def _is_active_legacy_entry(entry: dict[str, Any]) -> bool:
    return str(entry.get("legacy_path") or "").strip() == "CoachDecision"
