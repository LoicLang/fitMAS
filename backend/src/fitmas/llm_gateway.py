"""Unified LLM client layer for FitMAS.

Pure infrastructure — no fitmas domain imports.
All LLM calls (conversation, heartbeat, planning, onboarding) route through here.
"""
from __future__ import annotations

import json
import logging
import os
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def client():
    """Return an Anthropic client or None if unavailable."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Core request functions
# ---------------------------------------------------------------------------

def request_message(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
    cache_control: dict[str, Any] | None = None,
):
    """Send a message to the Anthropic API. Returns response or None."""
    c = client()
    if not c:
        return None
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if cache_control:
            kwargs["cache_control"] = cache_control
        return c.messages.create(**kwargs)
    except Exception:
        logger.exception("LLM message call failed")
        return None


def request_text(
    *, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512,
) -> str | None:
    """Request plain text response from LLM."""
    response = request_message(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
    )
    return message_text(response)


def request_json(
    *, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024,
) -> dict | None:
    """Request JSON response from LLM. Returns parsed dict or None.

    Parsing goes through _json_parse_candidates() so truncated tails and
    trailing noise from the model don't drop otherwise valid payloads."""
    raw = request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    return _robust_json_loads(raw)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def message_text(response: Any) -> str | None:
    """Extract concatenated text blocks from a response."""
    if response is None:
        return None
    texts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text = str(getattr(block, "text", "")).strip()
            if text:
                texts.append(text)
    if not texts:
        return None
    return "\n".join(texts).strip()


def message_json(response: Any) -> dict | None:
    """Extract and parse JSON from a response.

    Uses the same robust parser as request_json so truncated tails and
    trailing noise don't drop valid payloads."""
    raw = message_text(response)
    if not raw:
        return None
    return _robust_json_loads(raw)


def first_tool_use_block(response: Any) -> Any | None:
    """Find the first tool_use block in a response."""
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use":
            return block
    return None


def serialize_content_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    """Convert response content blocks to JSON-serializable dicts."""
    serialized: list[dict[str, Any]] = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            serialized.append({"type": "text", "text": getattr(block, "text", "")})
        elif block_type == "tool_use":
            serialized.append(
                {
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": dict(getattr(block, "input", {}) or {}),
                }
            )
    return serialized


# ---------------------------------------------------------------------------
# Robust JSON parsing
# ---------------------------------------------------------------------------

def _robust_json_loads(raw: str) -> dict | None:
    """Parse a (possibly messy) LLM string into a dict.

    Tries a small cascade of candidate repairs so trailing prose,
    truncated tails, or leading noise don't drop valid JSON payloads.
    Returns the first candidate that parses to a dict, else None."""
    cleaned = _strip_json_fences(raw)
    for candidate in _json_parse_candidates(cleaned):
        try:
            loaded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    logger.exception("Failed to decode LLM JSON: %s", cleaned[:200])
    return None


def _strip_json_fences(raw: str) -> str:
    candidate = raw.strip()
    if candidate.startswith("```"):
        parts = candidate.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
    if candidate.startswith("json"):
        candidate = candidate[4:]
    return candidate.strip()


def _json_parse_candidates(raw: str) -> list[str]:
    candidates: list[str] = []
    started = _slice_from_json_start(raw)
    for candidate in (
        raw.strip(),
        started,
        _balanced_json_prefix(started),
        _repair_truncated_json(started),
    ):
        normalized = str(candidate or "").strip()
        if not normalized or normalized in candidates:
            continue
        candidates.append(normalized)
    return candidates


def _slice_from_json_start(raw: str) -> str:
    start_positions = [pos for pos in (raw.find("{"), raw.find("[")) if pos >= 0]
    if not start_positions:
        return raw
    return raw[min(start_positions):].strip()


def _balanced_json_prefix(raw: str) -> str | None:
    if not raw:
        return None
    stack: list[str] = []
    in_string = False
    escape = False
    started = False
    for idx, char in enumerate(raw):
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
            started = True
            continue
        if char in "}]":
            if not stack:
                return None
            opener = stack.pop()
            if (opener, char) not in {("{", "}"), ("[", "]")}:
                return None
            if started and not stack:
                return raw[: idx + 1]
    return None


def _repair_truncated_json(raw: str) -> str | None:
    if not raw:
        return None
    buffer: list[str] = []
    stack: list[str] = []
    in_string = False
    escape = False
    for char in raw:
        buffer.append(char)
        if escape:
            escape = False
            continue
        if char == "\\" and in_string:
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "{[":
            stack.append(char)
            continue
        if char in "}]":
            if stack and (stack[-1], char) in {("{", "}"), ("[", "]")}:
                stack.pop()
    repaired = "".join(buffer).rstrip()
    if in_string:
        repaired += '"'
    if stack:
        repaired += "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return repaired.strip()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def usage_value(response: Any, key: str) -> int | None:
    """Extract a token count from response.usage."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    value = getattr(usage, key, None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def sum_ints(*values: int | None) -> int | None:
    """Sum multiple int|None values, ignoring None."""
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers)


def elapsed_ms(started_at: float) -> int:
    """Calculate elapsed milliseconds from perf_counter start."""
    return int((perf_counter() - started_at) * 1000)


# ---------------------------------------------------------------------------
# Heartbeat convenience
# ---------------------------------------------------------------------------

NO_SEND_TOKEN = "NO_SEND"

NO_SEND_INSTRUCTION = (
    "\n\nSi tu estimes qu'il n'y a rien d'utile ou de pertinent a dire "
    "en ce moment, reponds exactement NO_SEND (rien d'autre). "
    "Mieux vaut se taire que parler pour rien."
)


def generate_heartbeat_text(system: str, prompt: str, *, allow_no_send: bool = True) -> str | None:
    """Generate text for heartbeat messages. Returns None on failure or NO_SEND."""
    final_system = system
    if allow_no_send:
        final_system += NO_SEND_INSTRUCTION

    response = request_message(
        system=final_system,
        messages=[{"role": "user", "content": prompt}],
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
    )
    if response is None:
        return None

    text = message_text(response)
    if not text:
        return None

    # Check for NO_SEND token (exact match or wrapped in markup)
    cleaned = text.replace("*", "").replace("`", "").replace("#", "").strip()
    if cleaned.upper() == NO_SEND_TOKEN:
        logger.info("LLM opted out with NO_SEND")
        return None

    # NO_SEND + short ack (<100 chars) -> also suppress
    if NO_SEND_TOKEN in text.upper() and len(text) < 100:
        logger.info("LLM opted out with NO_SEND + short ack")
        return None

    # NO_SEND + real content -> strip token, deliver content
    if NO_SEND_TOKEN in text.upper():
        text = text.replace(NO_SEND_TOKEN, "").replace("no_send", "").strip()
        if not text:
            return None

    return text
