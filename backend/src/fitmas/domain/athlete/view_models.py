from __future__ import annotations

from pydantic import BaseModel, Field


class Profile(BaseModel):
    name: str
    age: int
    objective: str
    coaching_style: str
    primary_objective: str = ""
    weekly_structure_notes: str = ""
    coach_name: str = "FitMAS"
    coach_style: str = "direct"
    coach_relationship: str = ""
    coach_do: str = ""
    coach_dont: str = ""
    coach_soul: str = ""
    onboarding_status: str = "not_started"
    sports: list[str] = Field(default_factory=list)
    constraints: list[str]
    preferences: list[str]
    integrations: list[str]
