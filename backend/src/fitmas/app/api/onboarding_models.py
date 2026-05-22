from __future__ import annotations

from pydantic import BaseModel, Field

from fitmas.domain.planning.view_models import WeeklyPlan


class OnboardPreview(BaseModel):
    normalized_sports: list[str]
    setup_preview: list[str] = Field(default_factory=list)
    coach_preview: list[str]
    recap: str
    calibration_status: dict[str, object] | None = None


class OnboardResult(BaseModel):
    recap: str
    week_plan: WeeklyPlan
    calibration_status: dict[str, object] | None = None
