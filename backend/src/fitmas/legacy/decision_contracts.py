from __future__ import annotations

from pydantic import BaseModel


"""Temporary planning mutation compatibility contract.

Only `MutationDecision` remains here. Move it into the planning domain before
deleting `legacy/` completely.
"""

class MutationDecision(BaseModel):
    mutation_type: str
    target_session_id: int | None = None
    second_session_id: int | None = None
    target_date: str | None = None
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    new_sport_type: str | None = None
    new_session_type: str | None = None
    new_duration_min: int | None = None
    new_intensity: str | None = None
    new_description: str | None = None
    rationale: str
    fitmas_message: str


__all__ = [
    "MutationDecision",
]
