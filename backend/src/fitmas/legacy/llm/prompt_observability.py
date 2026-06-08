from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Sequence


class DecideFailureReason(StrEnum):
    NO_CLIENT = "no_client"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    EMPTY_OUTPUT = "empty_output"
    TOOL_LOOP_FAILED = "tool_loop_failed"
    TOOL_RESULT_MISSING = "tool_result_missing"
    INVALID_JSON = "invalid_json"
    SCHEMA_INVALID = "schema_invalid"
    REPAIR_FAILED = "repair_failed"
    FALLBACK_FAILED = "fallback_failed"
    VOICE_GUARD_INVALID = "voice_guard_invalid"
    FACTUAL_VERIFIER_BLOCKED = "factual_verifier_blocked"
    PROMPT_TOO_LONG = "prompt_too_long"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PromptTrace:
    route: str
    provider: str | None
    model: str | None
    prompt_policy: str | None
    prompt_contract: str | None
    intent: str | None
    system_chars: int
    user_chars: int
    total_chars: int
    tool_names: tuple[str, ...]
    truth_block_names: tuple[str, ...]
    history_messages_used: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_decide_failure_reason(raw: str | None) -> DecideFailureReason:
    if raw:
        try:
            return DecideFailureReason(str(raw).strip())
        except ValueError:
            return DecideFailureReason.UNKNOWN
    return DecideFailureReason.UNKNOWN


def build_prompt_trace(
    *,
    route: str,
    provider: str | None,
    model: str | None,
    prompt_policy: str | None,
    prompt_contract: str | None,
    intent: str | None,
    system: Sequence[dict[str, Any]] | str,
    user_prompt: str,
    tool_names: Sequence[str],
    truth_block_names: Sequence[str] = (),
    history_messages_used: int,
) -> PromptTrace:
    if isinstance(system, str):
        system_chars = len(system)
    else:
        system_chars = sum(len(str(part.get("text") or "")) for part in system)
    user_chars = len(user_prompt or "")
    return PromptTrace(
        route=route,
        provider=provider,
        model=model,
        prompt_policy=prompt_policy,
        prompt_contract=prompt_contract,
        intent=intent,
        system_chars=system_chars,
        user_chars=user_chars,
        total_chars=system_chars + user_chars,
        tool_names=tuple(str(name) for name in tool_names),
        truth_block_names=tuple(str(name) for name in truth_block_names),
        history_messages_used=int(history_messages_used or 0),
    )
