from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.decision import CoachUnderstanding, Command, CommandResult
from fitmas.decision import pending_resolution
from fitmas.decision.command_mapping import (
    CoachCommandBundle,
    commands_from_legacy_decision,
    commands_from_understanding,
    execution_action_from_command,
    memory_action_from_command,
)
from fitmas.domain.execution.mutation_service import apply_execution_actions_for_user
from fitmas.memory_mutation_service import apply_memory_actions_for_user


logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("fitmas.conversation_metrics")


@dataclass(slots=True)
class RuntimeCommandBus:
    db: Session
    user: s.User
    source: str = "coach_decision"
    conversation_turn_id: int | None = None

    def apply(self, commands: Sequence[Command]) -> tuple[CommandResult, ...]:
        results: list[CommandResult] = []
        for command in commands:
            if command.domain == "memory":
                results.append(self._apply_memory(command))
            elif command.domain == "execution":
                results.append(self._apply_execution(command))
            else:
                results.append(
                    CommandResult(
                        command_id=command.id,
                        domain=command.domain,
                        name=command.name,
                        status="blocked",
                        event_id=None,
                        payload={"reason": "unsupported_domain"},
                    )
                )
        return tuple(results)

    def _apply_memory(self, command: Command) -> CommandResult:
        try:
            action = memory_action_from_command(command)
        except Exception as exc:
            return CommandResult(
                command_id=command.id,
                domain="memory",
                name=command.name,
                status="blocked",
                event_id=None,
                payload={"reason": "invalid_memory_command", "error": str(exc)[:160]},
            )
        result = apply_memory_actions_for_user(
            self.db,
            user=self.user,
            actions=(action,),
            source=self.source,
            conversation_turn_id=self.conversation_turn_id,
        )
        status = "applied" if result.applied_count > 0 else "blocked" if result.blocked_count > 0 else "skipped"
        return CommandResult(
            command_id=command.id,
            domain="memory",
            name=command.name,
            status=status,
            event_id=_event_ref(result.event_ids),
            payload={
                "applied_count": result.applied_count,
                "blocked_count": result.blocked_count,
                "saved_keys": result.saved_keys,
                "event_ids": result.event_ids,
                "summary": _memory_summary(result.saved_keys),
                "reason": "memory_action_blocked" if result.blocked_count else "",
            },
        )

    def _apply_execution(self, command: Command) -> CommandResult:
        try:
            action = execution_action_from_command(command)
        except Exception as exc:
            return CommandResult(
                command_id=command.id,
                domain="execution",
                name=command.name,
                status="blocked",
                event_id=None,
                payload={"reason": "invalid_execution_command", "error": str(exc)[:160]},
            )
        result = apply_execution_actions_for_user(
            self.db,
            user=self.user,
            actions=(action,),
            source=self.source,
            conversation_turn_id=self.conversation_turn_id,
        )
        status = "applied" if result.applied_count > 0 else "blocked" if result.blocked_count > 0 else "skipped"
        return CommandResult(
            command_id=command.id,
            domain="execution",
            name=command.name,
            status=status,
            event_id=_event_ref(result.event_ids),
            payload={
                "applied_count": result.applied_count,
                "blocked_count": result.blocked_count,
                "updated_session_ids": result.updated_session_ids,
                "event_ids": result.event_ids,
                "summary": _execution_summary(result.updated_session_ids),
                "reason": "execution_action_blocked" if result.blocked_count else "",
            },
        )


def commands_from_understanding_enabled() -> bool:
    return _env_flag_enabled("FITMAS_COMMANDS_FROM_UNDERSTANDING", default=True)


def apply_understanding_commands(
    *,
    db: Session,
    user: s.User,
    understanding: CoachUnderstanding,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None = None,
    conversation_turn_id: int | None = None,
) -> dict[str, Any]:
    bundle = commands_from_understanding(understanding)
    return _apply_command_bundle(
        db=db,
        user=user,
        bundle=bundle,
        turn_memory_writes=turn_memory_writes,
        unresolved_execution_followup=unresolved_execution_followup,
        pending_resolution_artifact=pending_resolution.pending_resolution_from_sources(
            decision_artifact=None,
            canonical_understanding=understanding,
        ),
        conversation_turn_id=conversation_turn_id,
    )


def apply_coach_decision_commands(
    *,
    db: Session,
    user: s.User,
    decision_artifact: Any,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None = None,
    turn_plan: Any | None = None,
    canonical_understanding: CoachUnderstanding | None = None,
    conversation_turn_id: int | None = None,
) -> dict[str, Any]:
    bundle = _command_bundle(
        decision_artifact=decision_artifact,
        turn_plan=turn_plan,
        canonical_understanding=canonical_understanding,
    )
    pending_resolution_artifact = pending_resolution.pending_resolution_from_sources(
        decision_artifact=decision_artifact,
        canonical_understanding=canonical_understanding,
    )
    return _apply_command_bundle(
        db=db,
        user=user,
        bundle=bundle,
        turn_memory_writes=turn_memory_writes,
        unresolved_execution_followup=unresolved_execution_followup,
        pending_resolution_artifact=pending_resolution_artifact,
        conversation_turn_id=conversation_turn_id,
    )


def _apply_command_bundle(
    *,
    db: Session,
    user: s.User,
    bundle: CoachCommandBundle,
    turn_memory_writes: list[dict],
    unresolved_execution_followup: str | None,
    pending_resolution_artifact: Any,
    conversation_turn_id: int | None,
) -> dict[str, Any]:
    bus = RuntimeCommandBus(
        db=db,
        user=user,
        source=bundle.source,
        conversation_turn_id=conversation_turn_id,
    )
    results = bus.apply(bundle.commands)
    turn_memory_writes.extend(_turn_memory_writes_from_results(results, source=bundle.source))
    if bundle.deferred_execution_count:
        turn_memory_writes.append(
            {
                "category": "execution",
                "key": "record_execution_update",
                "value": f"deferred={bundle.deferred_execution_count}",
                "source": bundle.source,
                "action": "deferred",
            }
        )
    metrics = _metric_payload(results, deferred_execution_count=bundle.deferred_execution_count)
    metrics["command_source"] = bundle.source
    _log_metrics(
        user=user,
        bundle=bundle,
        metrics=metrics,
        unresolved_execution_followup=unresolved_execution_followup,
        pending_resolution=pending_resolution_artifact,
    )
    return metrics


def apply_turn_plan_memory_commands(
    *,
    db: Session,
    user: s.User,
    turn_plan: Any,
    turn_memory_writes: list[dict],
    turn_context: dict[str, object],
) -> None:
    bundle = commands_from_legacy_decision(_EmptyDecision(), turn_plan=turn_plan)
    if not bundle.commands:
        return
    bus = RuntimeCommandBus(db=db, user=user, source="turn_plan")
    results = bus.apply(tuple(command for command in bundle.commands if command.domain == "memory"))
    turn_memory_writes.extend(_turn_memory_writes_from_results(results, source="turn_plan"))
    metrics = _metric_payload(results, deferred_execution_count=0)
    turn_context["turn_plan_memory_action_result"] = {
        "memory_applied": metrics["memory_applied"],
        "memory_blocked": metrics["memory_blocked"],
        "saved_keys": [
            key
            for result in results
            for key in tuple(result.payload.get("saved_keys", ()) or ())
        ],
    }


class _EmptyDecision:
    memory_actions = ()
    execution_actions = ()
    response_type = "reply"
    plan_patch = None
    pending_resolution = None


def _command_bundle(
    *,
    decision_artifact: Any,
    turn_plan: Any | None,
    canonical_understanding: CoachUnderstanding | None,
) -> CoachCommandBundle:
    if commands_from_understanding_enabled() and isinstance(canonical_understanding, CoachUnderstanding):
        bundle = commands_from_understanding(canonical_understanding)
        if bundle.commands:
            return bundle
        logger.info("canonical_understanding_commands_empty falling_back_to_legacy_decision")
    return commands_from_legacy_decision(decision_artifact, turn_plan=turn_plan)


def _turn_memory_writes_from_results(results: tuple[CommandResult, ...], *, source: str) -> tuple[dict, ...]:
    writes: list[dict] = []
    for result in results:
        if result.domain == "memory":
            for saved_key in tuple(result.payload.get("saved_keys", ()) or ()):
                category, _, item_key = str(saved_key).partition(":")
                writes.append(
                    {
                        "category": category or "memory",
                        "key": item_key or str(saved_key),
                        "source": source,
                        "action": result.status,
                    }
                )
        elif result.domain == "execution":
            for session_id in tuple(result.payload.get("updated_session_ids", ()) or ()):
                writes.append(
                    {
                        "category": "execution",
                        "key": "record_execution_update",
                        "value": f"session_id={session_id}",
                        "source": source,
                        "action": result.status,
                    }
                )
            if result.status == "blocked":
                writes.append(
                    {
                        "category": "execution",
                        "key": "record_execution_update",
                        "value": "blocked=1",
                        "source": source,
                        "action": "blocked",
                    }
                )
    return tuple(writes)


def _metric_payload(results: tuple[CommandResult, ...], *, deferred_execution_count: int) -> dict[str, Any]:
    execution_updated_session_ids = tuple(
        session_id
        for result in results
        if result.domain == "execution"
        for session_id in tuple(result.payload.get("updated_session_ids", ()) or ())
    )
    return {
        "memory_applied": sum(int(result.payload.get("applied_count") or 0) for result in results if result.domain == "memory"),
        "memory_blocked": sum(int(result.payload.get("blocked_count") or 0) for result in results if result.domain == "memory"),
        "execution_applied": sum(int(result.payload.get("applied_count") or 0) for result in results if result.domain == "execution"),
        "execution_blocked": sum(int(result.payload.get("blocked_count") or 0) for result in results if result.domain == "execution"),
        "execution_deferred": deferred_execution_count,
        "execution_updated_session_ids": execution_updated_session_ids,
    }


def _log_metrics(
    *,
    user: s.User,
    bundle: CoachCommandBundle,
    metrics: dict[str, Any],
    unresolved_execution_followup: str | None,
    pending_resolution: Any,
) -> None:
    memory_count = sum(1 for command in bundle.commands if command.domain == "memory")
    execution_count = sum(1 for command in bundle.commands if command.domain == "execution")
    missing_execution_action = bool(unresolved_execution_followup and execution_count == 0)
    metrics_logger.info(
        "conversation_action_metrics user=%s memory_actions_per_turn=%s execution_actions_per_turn=%s pending_resolution_per_turn=%s llm_understanding_missing_action=%s memory_applied=%s execution_applied=%s command_source=%s",
        getattr(user, "id", None),
        memory_count,
        execution_count,
        1 if pending_resolution is not None else 0,
        1 if missing_execution_action else 0,
        metrics["memory_applied"],
        metrics["execution_applied"],
        bundle.source,
    )


def _event_ref(event_ids: tuple[int, ...]) -> str | None:
    if not event_ids:
        return None
    return f"memory_mutation_event:{event_ids[0]}"


def _memory_summary(saved_keys: tuple[str, ...]) -> str:
    if not saved_keys:
        return ""
    return "Memoire mise a jour: " + ", ".join(saved_keys)


def _execution_summary(updated_session_ids: tuple[int, ...]) -> str:
    if not updated_session_ids:
        return ""
    ids = ", ".join(str(item) for item in updated_session_ids)
    return f"Execution mise a jour: session_id={ids}"


def _env_flag_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
