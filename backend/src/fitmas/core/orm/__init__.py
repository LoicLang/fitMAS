from __future__ import annotations

from fitmas.core.orm.user import (
    User,
    UserConstraint,
    UserPreference,
    UserSport,
)

from fitmas.core.orm.memory import (
    UserFact,
    WorkingMemoryEntry,
    UserPattern,
    MemoryMutationEventRecord,
)

from fitmas.core.orm.execution import Activity

from fitmas.core.orm.integrations import StravaConnection

from fitmas.core.orm.planning import (
    WeeklyPlan,
    ScheduledSession,
    DayPlan,
    ChangeNote,
    WatchItem,
    PlanMutationEventRecord,
    PlanningDecisionRecord,
)

from fitmas.core.orm.coaching import (
    CoachMessage,
    ConversationTurnRecord,
    PendingMutationConfirmation,
    AdaptationEventRecord,
)

from fitmas.core.orm.athlete import (
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
