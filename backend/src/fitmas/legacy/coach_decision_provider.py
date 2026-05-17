from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Callable

from fitmas import llm as llm_runtime
from fitmas.legacy.coach_decision_artifact import (
    LegacyCoachDecisionArtifact,
    legacy_decision_artifact_from_raw,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CoachDecisionRequest:
    user_text: str
    plan_summary: str
    timeline_summary: str | None = None
    execution_summary: str | None = None
    temporal_summary: str | None = None
    activity_claim_summary: str | None = None
    signal_summary: str | None = None
    conversation_history: list[dict] | None = None
    coach_context: dict | None = None
    remembered_facts: list[dict] | None = None
    time_context: dict | None = None
    tool_context: Any | None = None


@dataclass(frozen=True, slots=True)
class CoachDecisionResult:
    artifact: LegacyCoachDecisionArtifact = field(
        default_factory=lambda: LegacyCoachDecisionArtifact(kind="none")
    )
    raw_decision: Any | None = None
    source: str = "legacy_coach_decision"
    error_type: str | None = None
    error_message: str | None = None
    decide_none_context: dict[str, Any] | None = None

    @property
    def decision(self) -> Any | None:
        return self.raw_decision

    @property
    def ok(self) -> bool:
        return self.artifact.has_value and self.error_type is None


class LegacyCoachDecisionProvider:
    def __init__(
        self,
        *,
        decide_fn: Callable[..., Any] | None = None,
        clear_fn: Callable[[], None] | None = None,
        get_decide_none_fn: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self._decide_fn = decide_fn or llm_runtime.decide
        self._clear_fn = clear_fn or llm_runtime.clear_last_decide_none
        self._get_decide_none_fn = get_decide_none_fn or llm_runtime.get_last_decide_none

    def decide(self, request: CoachDecisionRequest) -> CoachDecisionResult:
        try:
            self._clear_fn()
            raw_decision = self._decide_fn(
                request.user_text,
                request.plan_summary,
                timeline_summary=request.timeline_summary,
                execution_summary=request.execution_summary,
                temporal_summary=request.temporal_summary,
                activity_claim_summary=request.activity_claim_summary,
                signal_summary=request.signal_summary,
                conversation_history=request.conversation_history,
                coach_context=request.coach_context,
                remembered_facts=request.remembered_facts,
                time_context=request.time_context,
                tool_context=request.tool_context,
            )
            return CoachDecisionResult(
                artifact=legacy_decision_artifact_from_raw(raw_decision),
                raw_decision=raw_decision,
                decide_none_context=self._get_decide_none_fn(),
            )
        except Exception as exc:
            logger.exception("legacy_coach_decision_provider_failed")
            return CoachDecisionResult(
                artifact=LegacyCoachDecisionArtifact(kind="none"),
                raw_decision=None,
                error_type=type(exc).__name__,
                error_message=str(exc),
                decide_none_context=self._get_decide_none_fn(),
            )
