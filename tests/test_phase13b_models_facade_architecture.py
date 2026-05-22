from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "backend" / "src" / "fitmas"


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def test_13b_pydantic_contracts_live_in_owner_modules() -> None:
    assert _class_names(SRC / "decision" / "message_models.py") == {
        "MessageRole",
        "Message",
        "Extraction",
        "MessageReply",
    }
    assert _class_names(SRC / "domain" / "planning" / "view_models.py") == {
        "DayId",
        "ChangeNote",
        "WatchItem",
        "DayPlan",
        "WeeklyPlan",
        "ScheduledSession",
        "WorkoutContentView",
    }
    assert _class_names(SRC / "domain" / "athlete" / "view_models.py") == {"Profile"}
    assert _class_names(SRC / "domain" / "execution" / "view_models.py") == {"Activity"}
    assert _class_names(SRC / "domain" / "memory" / "view_models.py") == {"UserFact", "UserPattern"}
    assert _class_names(SRC / "app" / "api" / "onboarding_models.py") == {"OnboardPreview", "OnboardResult"}


def test_13b_owner_imports_resolve_without_root_models_facade() -> None:
    from fitmas.app.api.onboarding_models import OnboardResult
    from fitmas.app.api.read_models import TodayView
    from fitmas.decision.message_models import Extraction, MessageReply
    from fitmas.domain.execution.view_models import Activity
    from fitmas.domain.planning.view_models import DayId

    assert Activity.__name__ == "Activity"
    assert DayId.MONDAY.value == "monday"
    assert Extraction().confidence == 0.5
    assert MessageReply.__name__ == "MessageReply"
    assert OnboardResult.__name__ == "OnboardResult"
    assert TodayView.__name__ == "TodayView"
