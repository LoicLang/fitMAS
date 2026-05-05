from __future__ import annotations

from typing import Any

from fitmas.tools.contract import ToolContext, ToolResult


def draft_move_session(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    operation = {
        "operation_type": "move_session",
        "target_session_id": arguments.get("target_session_id"),
        "target_date": arguments.get("target_date"),
        "from_day": arguments.get("from_day"),
        "to_day": arguments.get("to_day"),
        "rationale": _rationale(arguments),
    }
    return _draft_single_operation(context, arguments, operation=operation, tool_name="draft_move_session")


def draft_swap_sessions(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    operation = {
        "operation_type": "swap_sessions",
        "target_session_id": arguments.get("target_session_id"),
        "second_session_id": arguments.get("second_session_id"),
        "rationale": _rationale(arguments),
    }
    return _draft_single_operation(context, arguments, operation=operation, tool_name="draft_swap_sessions")


def draft_replace_session(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    operation = {
        "operation_type": "replace_session",
        "target_session_id": arguments.get("target_session_id"),
        "new_title": arguments.get("new_title"),
        "new_goal": arguments.get("new_goal"),
        "new_sport_type": arguments.get("new_sport_type"),
        "new_session_type": arguments.get("new_session_type"),
        "new_duration_min": arguments.get("new_duration_min"),
        "new_intensity": arguments.get("new_intensity"),
        "new_description": arguments.get("new_description"),
        "rationale": _rationale(arguments),
    }
    return _draft_single_operation(context, arguments, operation=operation, tool_name="draft_replace_session")


def draft_lighten_day(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    operation = {
        "operation_type": "lighten_day",
        "target_session_id": arguments.get("target_session_id"),
        "new_title": arguments.get("new_title"),
        "new_goal": arguments.get("new_goal"),
        "new_duration_min": arguments.get("new_duration_min"),
        "new_intensity": arguments.get("new_intensity") or "easy",
        "new_description": arguments.get("new_description"),
        "rationale": _rationale(arguments),
    }
    return _draft_single_operation(context, arguments, operation=operation, tool_name="draft_lighten_day")


def draft_create_session(context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
    operation = {
        "operation_type": "create_session",
        "target_date": arguments.get("target_date"),
        "new_title": arguments.get("new_title"),
        "new_goal": arguments.get("new_goal"),
        "new_sport_type": arguments.get("new_sport_type"),
        "new_session_type": arguments.get("new_session_type"),
        "new_duration_min": arguments.get("new_duration_min"),
        "new_intensity": arguments.get("new_intensity"),
        "new_description": arguments.get("new_description"),
        "rationale": _rationale(arguments),
    }
    return _draft_single_operation(context, arguments, operation=operation, tool_name="draft_create_session")


def _draft_single_operation(
    context: ToolContext,
    arguments: dict[str, Any],
    *,
    operation: dict[str, Any],
    tool_name: str,
) -> ToolResult:
    from fitmas.plan_patch import PlanPatch, PlanPatchOperation, validate_plan_patch

    try:
        patch = PlanPatch(
            coach_message=str(arguments.get("coach_message") or "Patch candidat a valider."),
            confirmation_reason=_optional_str(arguments.get("confirmation_reason")),
            operations=[PlanPatchOperation.model_validate(_drop_none(operation))],
        )
    except Exception as exc:
        return ToolResult(
            tool_name=tool_name,
            status="error",
            error=f"invalid_plan_patch_candidate: {exc}",
            summary="Candidate invalide: schema PlanPatch non respecte.",
        )

    validation = validate_plan_patch(
        context.db,
        plan_id=0,
        patch=patch,
        scheduled_sessions=context.scheduled_sessions,
        timezone_name=context.timezone_name,
    )
    payload = {
        "patch": patch.model_dump(exclude_none=True),
        "validation": _validation_payload(validation),
        "next_step": _next_step(validation.status),
        "commit_performed": False,
        "writer": "none",
    }
    return ToolResult(
        tool_name=tool_name,
        status="ok",
        payload=payload,
        summary=_summary_for_candidate(tool_name, validation),
    )


def _validation_payload(validation: Any) -> dict[str, Any]:
    return {
        "status": validation.status,
        "summary": validation.summary,
        "operation_results": [
            {
                "operation_type": result.operation_type,
                "status": result.status,
                "target_session_id": result.target_session_id,
                "block_reason": result.block_reason,
                "warning_codes": list(result.warning_codes),
                "warning_messages": list(result.warning_messages),
                "suggested_fix": result.suggested_fix,
            }
            for result in validation.operation_results
        ],
    }


def _summary_for_candidate(tool_name: str, validation: Any) -> str:
    label = tool_name.removeprefix("draft_")
    return f"Candidate {label}: {validation.summary} Aucun commit effectue."


def _next_step(status: str) -> str:
    if status == "valid":
        return "return_plan_patch"
    if status in {"warning", "requires_confirmation"}:
        return "return_requires_confirmation"
    return "do_not_commit"


def _rationale(arguments: dict[str, Any]) -> str:
    return str(arguments.get("rationale") or "Action planning candidate.").strip()


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _optional_str(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None
