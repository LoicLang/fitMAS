from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DecisionExplanation:
    decision_label: str
    reason_summary: str
    evidence: tuple[str, ...]
    tradeoff: str | None
    impact: Mapping[str, Any]
    protected: tuple[str, ...]
    next_step: str | None
