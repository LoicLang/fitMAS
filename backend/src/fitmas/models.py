from __future__ import annotations

from fitmas.app.api.onboarding_models import OnboardPreview, OnboardResult
from fitmas.app.api.payloads import MoveSessionPayload
from fitmas.app.api.read_models import RecentSportActivity, TodayFitness, TodayView
from fitmas.decision.message_models import Extraction, Message, MessageReply, MessageRole
from fitmas.domain.athlete.view_models import Profile
from fitmas.domain.execution.view_models import Activity
from fitmas.domain.memory.view_models import UserFact, UserPattern
from fitmas.domain.planning.view_models import (
    ChangeNote,
    DayId,
    DayPlan,
    ScheduledSession,
    WatchItem,
    WeeklyPlan,
    WorkoutContentView,
)

__all__ = [
    "Activity",
    "ChangeNote",
    "DayId",
    "DayPlan",
    "Extraction",
    "Message",
    "MessageReply",
    "MessageRole",
    "MoveSessionPayload",
    "OnboardPreview",
    "OnboardResult",
    "Profile",
    "RecentSportActivity",
    "ScheduledSession",
    "TodayFitness",
    "TodayView",
    "UserFact",
    "UserPattern",
    "WatchItem",
    "WeeklyPlan",
    "WorkoutContentView",
]
