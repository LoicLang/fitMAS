from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TelegramDebounceState:
    pending_messages: list[str] = field(default_factory=list)
    in_flight: bool = False


_STATE_BY_CHAT: dict[int, TelegramDebounceState] = {}


def enqueue_message(chat_id: int, text: str) -> int:
    state = _STATE_BY_CHAT.setdefault(chat_id, TelegramDebounceState())
    cleaned = (text or "").strip()
    if cleaned:
        state.pending_messages.append(cleaned)
    return len(state.pending_messages)


def consume_messages(chat_id: int) -> list[str]:
    state = _STATE_BY_CHAT.get(chat_id)
    if state is None or not state.pending_messages:
        return []
    batch = list(state.pending_messages)
    state.pending_messages.clear()
    _cleanup_if_idle(chat_id, state)
    return batch


def has_pending_messages(chat_id: int) -> bool:
    state = _STATE_BY_CHAT.get(chat_id)
    return bool(state and state.pending_messages)


def mark_in_flight(chat_id: int, value: bool) -> None:
    state = _STATE_BY_CHAT.setdefault(chat_id, TelegramDebounceState())
    state.in_flight = value
    _cleanup_if_idle(chat_id, state)


def is_in_flight(chat_id: int) -> bool:
    state = _STATE_BY_CHAT.get(chat_id)
    return bool(state and state.in_flight)


def build_batched_text(messages: list[str]) -> str:
    return "\n".join(part.strip() for part in messages if part and part.strip())


def reset_state(chat_id: int) -> None:
    _STATE_BY_CHAT.pop(chat_id, None)


def _cleanup_if_idle(chat_id: int, state: TelegramDebounceState) -> None:
    if state.in_flight or state.pending_messages:
        return
    _STATE_BY_CHAT.pop(chat_id, None)
