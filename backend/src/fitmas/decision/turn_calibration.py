from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from fitmas.calibration_llm import extract_calibration_resolution
from fitmas.calibration_needs import (
    build_resolution_memory_updates,
    find_open_calibration_need,
    should_apply_calibration_resolution,
)
from fitmas.conversation_contract import ConversationTurnInput, ConversationTurnState
from fitmas.decision import turn_persistence
from fitmas.decision import turn_state


@dataclass(slots=True)
class TurnCalibrationResult:
    open_calibration_need: object | None
    calibration_resolution: object | None


def apply_turn_calibration(
    *,
    db: Session,
    user,
    payload: ConversationTurnInput,
    state: ConversationTurnState,
    turn_memory_writes: list[dict],
) -> TurnCalibrationResult:
    open_calibration_need = find_open_calibration_need(state.active_memory_rows)
    calibration_resolution = None
    if open_calibration_need is not None:
        calibration_resolution = extract_calibration_resolution(
            user_text=payload.text,
            need=open_calibration_need,
            timezone_name=user.timezone,
            coach_context={
                "coach_name": user.coach_name,
                "coach_style": user.coach_style,
                "coach_relationship": user.coach_relationship,
                "coach_do": user.coach_do,
                "coach_dont": user.coach_dont,
                "coach_soul": user.coach_soul,
            },
        )
        if should_apply_calibration_resolution(calibration_resolution):
            turn_persistence.persist_turn_memory_updates(
                db,
                user.id,
                build_resolution_memory_updates(open_calibration_need, calibration_resolution),
                turn_memory_writes=turn_memory_writes,
            )
            state.active_memory_rows, state.active_facts = turn_state.active_memory_payloads(db, user.id)

    return TurnCalibrationResult(
        open_calibration_need=open_calibration_need,
        calibration_resolution=calibration_resolution,
    )
