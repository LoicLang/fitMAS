from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from fitmas.core import orm as s
from fitmas.domain.memory.fact_memory import fact_is_current, normalize_fact_payload
from fitmas.domain.memory.view_models import UserFact, UserPattern


def to_pydantic_fact(fact: object) -> UserFact:
    return UserFact(
        category=str(getattr(fact, "category", "")),
        key=str(getattr(fact, "key", "")),
        value=str(getattr(fact, "value", "")),
        source=str(getattr(fact, "source", "conversation")),
        confidence=float(getattr(fact, "confidence", 0.0) or 0.0),
        confirmed=bool(getattr(fact, "confirmed", False)),
        active=bool(getattr(fact, "active", True)),
        urgency=str(getattr(fact, "urgency", "medium")),
        ttl=str(getattr(fact, "ttl", "medium")),
        affects=_json_loads_list(str(getattr(fact, "affects_json", "[]") or "[]")),
        expires_at=getattr(fact, "expires_at", None).isoformat() if getattr(fact, "expires_at", None) else None,
        status=str(getattr(fact, "status", "open") or "open"),
        severity=str(getattr(fact, "severity", "medium") or "medium"),
        signal_kind=str(getattr(fact, "signal_kind", "") or ""),
        observed_at=getattr(fact, "observed_at", None).isoformat() if getattr(fact, "observed_at", None) else None,
        valid_from=getattr(fact, "valid_from", None).isoformat() if getattr(fact, "valid_from", None) else None,
        valid_until=getattr(fact, "valid_until", None).isoformat() if getattr(fact, "valid_until", None) else None,
        last_seen_at=getattr(fact, "last_seen_at", None).isoformat() if getattr(fact, "last_seen_at", None) else None,
        resolved_at=getattr(fact, "resolved_at", None).isoformat() if getattr(fact, "resolved_at", None) else None,
        resolution_reason=str(getattr(fact, "resolution_reason", "") or ""),
    )


def to_pydantic_pattern(pattern: s.UserPattern) -> UserPattern:
    return UserPattern(
        category=pattern.category,
        pattern_type=pattern.pattern_type,
        key=pattern.key,
        value=pattern.value,
        source=pattern.source,
        confidence=float(pattern.confidence or 0.0),
        confirmed=bool(pattern.confirmed),
        active=bool(pattern.active),
        urgency=pattern.urgency,
        ttl=pattern.ttl,
        evidence_count=int(pattern.evidence_count or 0),
        affects=_json_loads_list(pattern.affects_json),
        first_seen_at=pattern.first_seen_at.isoformat() if pattern.first_seen_at else None,
        last_seen_at=pattern.last_seen_at.isoformat() if pattern.last_seen_at else None,
    )


def get_active_facts(db: Session, user_id: int, limit: int = 12) -> list[s.UserFact]:
    rows = (
        db.query(s.UserFact)
        .filter(s.UserFact.user_id == user_id, s.UserFact.active.is_(True))
        .order_by(s.UserFact.confirmed.desc(), s.UserFact.confidence.desc(), s.UserFact.updated_at.desc())
        .limit(max(limit * 4, 24))
        .all()
    )
    return [row for row in rows if fact_is_current(row)][:limit]


def get_active_working_memory(db: Session, user_id: int, limit: int = 12) -> list[s.WorkingMemoryEntry]:
    rows = (
        db.query(s.WorkingMemoryEntry)
        .filter(s.WorkingMemoryEntry.user_id == user_id, s.WorkingMemoryEntry.active.is_(True))
        .order_by(
            s.WorkingMemoryEntry.confirmed.desc(),
            s.WorkingMemoryEntry.confidence.desc(),
            s.WorkingMemoryEntry.updated_at.desc(),
        )
        .limit(max(limit * 4, 24))
        .all()
    )
    return [row for row in rows if fact_is_current(row)][:limit]


def get_active_patterns(db: Session, user_id: int, limit: int = 6) -> list[s.UserPattern]:
    rows = (
        db.query(s.UserPattern)
        .filter(s.UserPattern.user_id == user_id, s.UserPattern.active.is_(True))
        .order_by(
            s.UserPattern.confirmed.desc(),
            s.UserPattern.confidence.desc(),
            s.UserPattern.evidence_count.desc(),
            s.UserPattern.updated_at.desc(),
        )
        .limit(max(limit * 4, 24))
        .all()
    )
    return [row for row in rows if fact_is_current(row)][:limit]


def get_active_memory_items(
    db: Session,
    user_id: int,
    *,
    profile_limit: int = 12,
    working_limit: int = 12,
    include_patterns: bool = False,
    pattern_limit: int = 6,
    total_limit: int = 24,
) -> list[object]:
    items = [
        *get_active_facts(db, user_id, limit=profile_limit),
        *get_active_working_memory(db, user_id, limit=working_limit),
    ]
    if include_patterns:
        items.extend(get_active_patterns(db, user_id, limit=pattern_limit))
    items.sort(
        key=lambda row: (
            bool(getattr(row, "confirmed", False)),
            float(getattr(row, "confidence", 0.0) or 0.0),
            float(getattr(row, "evidence_count", 0) or 0),
            getattr(row, "updated_at", None) or getattr(row, "created_at", None),
        ),
        reverse=True,
    )
    return items[:total_limit]


def replace_user_facts(db: Session, user_id: int, facts: list[dict]) -> None:
    db.query(s.UserFact).filter(s.UserFact.user_id == user_id).delete()
    for fact in facts:
        normalized = normalize_fact_payload(fact)
        db.add(
            s.UserFact(
                user_id=user_id,
                category=normalized["category"],
                key=normalized["key"],
                value=normalized["value"],
                source=normalized.get("source", "onboarding"),
                confidence=normalized.get("confidence", 1.0),
                confirmed=normalized.get("confirmed", True),
                active=normalized.get("active", True),
                urgency=normalized.get("urgency", "medium"),
                ttl=normalized.get("ttl", "medium"),
                affects_json=_json_dumps(normalized.get("affects", [])),
                expires_at=normalized.get("expires_at"),
                status=normalized.get("status", "open"),
                severity=normalized.get("severity", "medium"),
                signal_kind=normalized.get("signal_kind", ""),
                observed_at=normalized.get("observed_at"),
                valid_from=normalized.get("valid_from"),
                valid_until=normalized.get("valid_until"),
                last_seen_at=normalized.get("last_seen_at"),
                resolved_at=normalized.get("resolved_at"),
                resolution_reason=normalized.get("resolution_reason", ""),
            )
        )
    db.commit()


def upsert_facts(db: Session, user_id: int, facts: list[dict]) -> list[s.UserFact]:
    saved: list[s.UserFact] = []
    for fact in facts:
        normalized = normalize_fact_payload(fact)
        category = normalized.get("category", "").strip()
        key = normalized.get("key", "").strip()
        value = normalized.get("value", "").strip()
        if not category or not key:
            continue

        row = (
            db.query(s.UserFact)
            .filter(s.UserFact.user_id == user_id, s.UserFact.category == category, s.UserFact.key == key)
            .first()
        )
        action = fact.get("action", "upsert")

        if action == "archive":
            if row:
                row.active = False
                if value:
                    row.value = value
                saved.append(row)
            continue

        if not value:
            continue

        if row is None:
            row = s.UserFact(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                source=normalized.get("source", "conversation"),
                confidence=float(normalized.get("confidence", 0.7)),
                confirmed=bool(normalized.get("confirmed", False)),
                active=True,
                urgency=normalized.get("urgency", "medium"),
                ttl=normalized.get("ttl", "medium"),
                affects_json=_json_dumps(normalized.get("affects", [])),
                expires_at=normalized.get("expires_at"),
                status=normalized.get("status", "open"),
                severity=normalized.get("severity", "medium"),
                signal_kind=normalized.get("signal_kind", ""),
                observed_at=normalized.get("observed_at"),
                valid_from=normalized.get("valid_from"),
                valid_until=normalized.get("valid_until"),
                last_seen_at=normalized.get("last_seen_at"),
                resolved_at=normalized.get("resolved_at"),
                resolution_reason=normalized.get("resolution_reason", ""),
            )
            db.add(row)
        else:
            row.value = value
            row.source = normalized.get("source", row.source)
            row.confidence = max(row.confidence, float(normalized.get("confidence", row.confidence)))
            row.confirmed = row.confirmed or bool(normalized.get("confirmed", False))
            row.active = True
            row.urgency = normalized.get("urgency", row.urgency)
            row.ttl = normalized.get("ttl", row.ttl)
            row.affects_json = _json_dumps(normalized.get("affects", _json_loads_list(row.affects_json)))
            row.expires_at = normalized.get("expires_at")
            row.status = normalized.get("status", row.status)
            row.severity = normalized.get("severity", row.severity)
            row.signal_kind = normalized.get("signal_kind", row.signal_kind)
            row.observed_at = normalized.get("observed_at", row.observed_at)
            row.valid_from = normalized.get("valid_from", row.valid_from)
            row.valid_until = normalized.get("valid_until", row.valid_until)
            row.last_seen_at = normalized.get("last_seen_at", row.last_seen_at)
            row.resolved_at = normalized.get("resolved_at", row.resolved_at)
            row.resolution_reason = normalized.get("resolution_reason", row.resolution_reason)

        saved.append(row)

    db.commit()
    return saved


def upsert_working_memory(db: Session, user_id: int, entries: list[dict]) -> list[s.WorkingMemoryEntry]:
    saved: list[s.WorkingMemoryEntry] = []
    for entry in entries:
        normalized = normalize_fact_payload(entry)
        category = normalized.get("category", "").strip()
        key = normalized.get("key", "").strip()
        value = normalized.get("value", "").strip()
        if not category or not key:
            continue

        row = (
            db.query(s.WorkingMemoryEntry)
            .filter(
                s.WorkingMemoryEntry.user_id == user_id,
                s.WorkingMemoryEntry.category == category,
                s.WorkingMemoryEntry.key == key,
            )
            .first()
        )
        action = entry.get("action", "upsert")

        if action == "archive":
            if row:
                row.active = False
                if value:
                    row.value = value
                saved.append(row)
            continue

        if not value:
            continue

        scope = str(entry.get("scope") or "conversation")
        if row is None:
            row = s.WorkingMemoryEntry(
                user_id=user_id,
                category=category,
                key=key,
                value=value,
                source=normalized.get("source", "conversation"),
                confidence=float(normalized.get("confidence", 0.7)),
                confirmed=bool(normalized.get("confirmed", False)),
                active=True,
                urgency=normalized.get("urgency", "medium"),
                ttl=normalized.get("ttl", "short"),
                scope=scope,
                affects_json=_json_dumps(normalized.get("affects", [])),
                expires_at=normalized.get("expires_at"),
                status=normalized.get("status", "open"),
                severity=normalized.get("severity", "medium"),
                signal_kind=normalized.get("signal_kind", ""),
                observed_at=normalized.get("observed_at"),
                valid_from=normalized.get("valid_from"),
                valid_until=normalized.get("valid_until"),
                last_seen_at=normalized.get("last_seen_at"),
                resolved_at=normalized.get("resolved_at"),
                resolution_reason=normalized.get("resolution_reason", ""),
            )
            db.add(row)
        else:
            row.value = value
            row.source = normalized.get("source", row.source)
            row.confidence = max(row.confidence, float(normalized.get("confidence", row.confidence)))
            row.confirmed = row.confirmed or bool(normalized.get("confirmed", False))
            row.active = True
            row.urgency = normalized.get("urgency", row.urgency)
            row.ttl = normalized.get("ttl", row.ttl)
            row.scope = scope or row.scope
            row.affects_json = _json_dumps(normalized.get("affects", _json_loads_list(row.affects_json)))
            row.expires_at = normalized.get("expires_at")
            row.status = normalized.get("status", row.status)
            row.severity = normalized.get("severity", row.severity)
            row.signal_kind = normalized.get("signal_kind", row.signal_kind)
            row.observed_at = normalized.get("observed_at", row.observed_at)
            row.valid_from = normalized.get("valid_from", row.valid_from)
            row.valid_until = normalized.get("valid_until", row.valid_until)
            row.last_seen_at = normalized.get("last_seen_at", row.last_seen_at)
            row.resolved_at = normalized.get("resolved_at", row.resolved_at)
            row.resolution_reason = normalized.get("resolution_reason", row.resolution_reason)

        saved.append(row)

    db.commit()
    return saved


def purge_expired_working_memory(db: Session, user_id: int | None = None) -> int:
    query = db.query(s.WorkingMemoryEntry).filter(s.WorkingMemoryEntry.active.is_(True))
    if user_id is not None:
        query = query.filter(s.WorkingMemoryEntry.user_id == user_id)
    rows = query.all()
    archived = 0
    for row in rows:
        if fact_is_current(row):
            continue
        row.active = False
        archived += 1
    if archived:
        db.commit()
    return archived


def sync_user_patterns(db: Session, user_id: int, patterns: list[dict]) -> tuple[int, int]:
    normalized_patterns = [dict(pattern) for pattern in patterns]
    active_keys = {
        (str(pattern.get("pattern_type") or "").strip(), str(pattern.get("key") or "").strip())
        for pattern in normalized_patterns
        if str(pattern.get("pattern_type") or "").strip() and str(pattern.get("key") or "").strip()
    }
    existing_rows = (
        db.query(s.UserPattern)
        .filter(s.UserPattern.user_id == user_id)
        .all()
    )
    by_identity = {
        (row.pattern_type, row.key): row
        for row in existing_rows
    }
    upserted = 0
    archived = 0

    for pattern in normalized_patterns:
        category = str(pattern.get("category") or "").strip()
        pattern_type = str(pattern.get("pattern_type") or "").strip()
        key = str(pattern.get("key") or "").strip()
        value = str(pattern.get("value") or "").strip()
        if not category or not pattern_type or not key or not value:
            continue

        row = by_identity.get((pattern_type, key))
        if row is None:
            row = s.UserPattern(
                user_id=user_id,
                category=category,
                pattern_type=pattern_type,
                key=key,
                value=value,
                source=str(pattern.get("source") or "maintenance"),
                confidence=float(pattern.get("confidence", 0.7) or 0.7),
                confirmed=bool(pattern.get("confirmed", True)),
                active=True,
                urgency=str(pattern.get("urgency") or "medium"),
                ttl=str(pattern.get("ttl") or "long"),
                evidence_count=int(pattern.get("evidence_count", 1) or 1),
                affects_json=_json_dumps(pattern.get("affects", [])),
                metadata_json=_json_dumps(pattern.get("metadata", {})),
                first_seen_at=pattern.get("first_seen_at"),
                last_seen_at=pattern.get("last_seen_at"),
            )
            db.add(row)
            by_identity[(pattern_type, key)] = row
        else:
            row.category = category
            row.value = value
            row.source = str(pattern.get("source") or row.source)
            row.confidence = float(pattern.get("confidence", row.confidence) or row.confidence)
            row.confirmed = bool(pattern.get("confirmed", row.confirmed))
            row.active = True
            row.urgency = str(pattern.get("urgency") or row.urgency)
            row.ttl = str(pattern.get("ttl") or row.ttl)
            row.evidence_count = int(pattern.get("evidence_count", row.evidence_count) or row.evidence_count)
            row.affects_json = _json_dumps(pattern.get("affects", _json_loads_list(row.affects_json)))
            row.metadata_json = _json_dumps(pattern.get("metadata", _json_loads_json(row.metadata_json)))
            row.first_seen_at = pattern.get("first_seen_at") or row.first_seen_at
            row.last_seen_at = pattern.get("last_seen_at") or row.last_seen_at
        upserted += 1

    for row in existing_rows:
        identity = (row.pattern_type, row.key)
        if row.source != "maintenance" or identity in active_keys or not row.active:
            continue
        row.active = False
        archived += 1

    db.commit()
    return upserted, archived


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=_json_default)


def _json_loads_list(raw_value: str) -> list[str]:
    if not raw_value:
        return []
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _json_loads_json(raw_value: str) -> dict[str, object]:
    if not raw_value:
        return {}
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
