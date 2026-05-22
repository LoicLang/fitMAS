from __future__ import annotations

from pydantic import BaseModel, Field


class UserFact(BaseModel):
    category: str
    key: str
    value: str
    source: str
    confidence: float
    confirmed: bool
    active: bool
    urgency: str = "medium"
    ttl: str = "medium"
    affects: list[str] = Field(default_factory=list)
    expires_at: str | None = None
    status: str = "open"
    severity: str = "medium"
    signal_kind: str = ""
    observed_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    last_seen_at: str | None = None
    resolved_at: str | None = None
    resolution_reason: str = ""


class UserPattern(BaseModel):
    category: str
    pattern_type: str
    key: str
    value: str
    source: str
    confidence: float
    confirmed: bool
    active: bool
    urgency: str = "medium"
    ttl: str = "long"
    evidence_count: int = 1
    affects: list[str] = Field(default_factory=list)
    first_seen_at: str | None = None
    last_seen_at: str | None = None
