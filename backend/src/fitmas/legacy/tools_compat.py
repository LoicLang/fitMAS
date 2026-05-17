from __future__ import annotations

from collections.abc import Sequence

from fitmas import plan_patch_tools
from fitmas.tools.contract import ToolContext, ToolResult, ToolSpec
from fitmas.tools.registry import _build_replan_candidate_result


def legacy_planning_tool_specs() -> Sequence[ToolSpec]:
    return (
        ToolSpec(
            name="draft_move_session",
            description="Legacy compat: construit un PlanPatch candidat move_session sans ecriture.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer"},
                    "target_date": {"type": "string"},
                    "from_day": {"type": "string"},
                    "to_day": {"type": "string"},
                    "rationale": {"type": "string"},
                    "coach_message": {"type": "string"},
                    "confirmation_reason": {"type": "string"},
                },
                "required": ["target_session_id", "target_date", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_move_session,
        ),
        ToolSpec(
            name="draft_swap_sessions",
            description="Legacy compat: construit un PlanPatch candidat swap_sessions sans ecriture.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer"},
                    "second_session_id": {"type": "integer"},
                    "rationale": {"type": "string"},
                    "coach_message": {"type": "string"},
                    "confirmation_reason": {"type": "string"},
                },
                "required": ["target_session_id", "second_session_id", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_swap_sessions,
        ),
        ToolSpec(
            name="draft_replace_session",
            description="Legacy compat: construit un PlanPatch candidat replace_session sans ecriture.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer"},
                    "new_title": {"type": "string"},
                    "new_goal": {"type": "string"},
                    "new_sport_type": {"type": "string"},
                    "new_session_type": {"type": "string"},
                    "new_duration_min": {"type": "integer"},
                    "new_intensity": {"type": "string"},
                    "new_description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "coach_message": {"type": "string"},
                    "confirmation_reason": {"type": "string"},
                },
                "required": ["target_session_id", "new_sport_type", "new_title", "new_duration_min", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_replace_session,
        ),
        ToolSpec(
            name="draft_lighten_day",
            description="Legacy compat: construit un PlanPatch candidat update_session/lighten sans ecriture.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_session_id": {"type": "integer"},
                    "new_title": {"type": "string"},
                    "new_goal": {"type": "string"},
                    "new_duration_min": {"type": "integer"},
                    "new_intensity": {"type": "string"},
                    "new_description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "coach_message": {"type": "string"},
                    "confirmation_reason": {"type": "string"},
                },
                "required": ["target_session_id", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_lighten_day,
        ),
        ToolSpec(
            name="draft_create_session",
            description="Legacy compat: construit un PlanPatch candidat create_session sans ecriture.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "target_date": {"type": "string"},
                    "new_title": {"type": "string"},
                    "new_goal": {"type": "string"},
                    "new_sport_type": {"type": "string"},
                    "new_session_type": {"type": "string"},
                    "new_duration_min": {"type": "integer"},
                    "new_intensity": {"type": "string"},
                    "new_description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "coach_message": {"type": "string"},
                    "confirmation_reason": {"type": "string"},
                },
                "required": ["target_date", "new_sport_type", "new_title", "new_duration_min", "rationale", "coach_message"],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=plan_patch_tools.draft_create_session,
        ),
        ToolSpec(
            name="propose_replan",
            description="Legacy compat: alias read-only de suggest_replan_candidates.",
            kind="candidate",
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "sport_type": {"type": "string"},
                    "preferred_replacement_sport": {"type": "string"},
                },
                "required": [],
            },
            allowed_pipelines=("conversation", "planning"),
            handler=_propose_replan,
        ),
    )


def _propose_replan(context: ToolContext, arguments: dict[str, object]) -> ToolResult:
    return _build_replan_candidate_result(context, arguments, tool_name="propose_replan")
