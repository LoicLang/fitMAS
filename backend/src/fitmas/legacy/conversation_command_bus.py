from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from fitmas import schema as s
from fitmas.decision import Command, CommandResult
from fitmas.execution_mutation_service import apply_execution_actions_for_user
from fitmas.legacy.coach_command_adapter import execution_action_from_command, memory_action_from_command
from fitmas.memory_mutation_service import apply_memory_actions_for_user


@dataclass(slots=True)
class ConversationCommandBus:
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
