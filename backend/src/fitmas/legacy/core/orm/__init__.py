from __future__ import annotations

from fitmas.legacy.core.orm.user import (
    User,
    UserConstraint,
    UserPreference,
    UserSport,
)

from fitmas.legacy.core.orm.memory import (
    UserFact,
    WorkingMemoryEntry,
    UserPattern,
    MemoryMutationEventRecord,
)

from fitmas.legacy.core.orm.execution import Activity

from fitmas.legacy.core.orm.integrations import StravaConnection

from fitmas.legacy.core.orm.planning import (
    WeeklyPlan,
    ScheduledSession,
    DayPlan,
    ChangeNote,
    WatchItem,
    PlanMutationEventRecord,
    PlanningDecisionRecord,
)

from fitmas.legacy.core.orm.coaching import (
    CoachMessage,
    ConversationTurnRecord,
    PendingMutationConfirmation,
    AdaptationEventRecord,
)

from fitmas.legacy.core.orm.athlete import (
    FitnessSnapshotRecord,
    ReadinessSnapshotRecord,
)

__all__ = [
    "Activity",
    "AdaptationEventRecord",
    "ChangeNote",
    "CoachMessage",
    "ConversationTurnRecord",
    "DayPlan",
    "FitnessSnapshotRecord",
    "MemoryMutationEventRecord",
    "PendingMutationConfirmation",
    "PlanMutationEventRecord",
    "PlanningDecisionRecord",
    "ReadinessSnapshotRecord",
    "ScheduledSession",
    "StravaConnection",
    "User",
    "UserConstraint",
    "UserFact",
    "UserPattern",
    "UserPreference",
    "UserSport",
    "WatchItem",
    "WeeklyPlan",
    "WorkingMemoryEntry",
]
