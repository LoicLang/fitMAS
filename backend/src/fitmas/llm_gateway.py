"""Unified LLM client layer for FitMAS.

Pure infrastructure — no fitmas domain imports.
All LLM calls (conversation, heartbeat, planning, onboarding) route through here.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)

DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_OPENAI_BASE_URL = "https://api.deepseek.com"
DEFAULT_FAST_MODEL = "deepseek-v4-flash"
DEFAULT_STRONG_MODEL = "deepseek-v4-pro"
DEFAULT_MODEL = DEFAULT_STRONG_MODEL
_CLAUDE_FAST_MODELS = {"claude-haiku-4-5-20251001"}
_CLAUDE_STRONG_MODELS = {"claude-sonnet-4-6"}
CLAUDE_FALLBACK_MODEL = "claude-haiku-4-5-20251001"
DEEPSEEK_STRUCTURED_MIN_TOKENS = 3072
DEEPSEEK_STRUCTURED_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class StructuredJSONResult:
    data: dict | None
    provider: str
    model: str
    raw_text: str | None = None
    error: str | None = None
    json_repair_used: bool = False
    provider_fallback_used: bool = False


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def client():
    """Return the configured Anthropic-compatible client or None if unavailable."""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    api_key = deepseek_key or anthropic_key
    if not api_key:
        return None
    try:
        import anthropic
        if deepseek_key:
            return anthropic.Anthropic(api_key=api_key, base_url=DEEPSEEK_ANTHROPIC_BASE_URL)
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def anthropic_client(*, provider: str = "auto"):
    """Return an Anthropic-compatible client for auto/deepseek/claude."""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    try:
        import anthropic
    except ImportError:
        return None

    if provider == "claude":
        if not anthropic_key:
            return None
        return anthropic.Anthropic(api_key=anthropic_key)
    if provider == "deepseek":
        if not deepseek_key:
            return None
        return anthropic.Anthropic(api_key=deepseek_key, base_url=DEEPSEEK_ANTHROPIC_BASE_URL)
    return client()


def deepseek_openai_client():
    """Return a DeepSeek OpenAI-compatible client or None."""
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not deepseek_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI(api_key=deepseek_key, base_url=DEEPSEEK_OPENAI_BASE_URL)


def _normalize_model_for_provider(model: str) -> str:
    """Map legacy Claude model names to current DeepSeek V4 equivalents."""
    if not os.getenv("DEEPSEEK_API_KEY"):
        return model
    if model in _CLAUDE_FAST_MODELS:
        return DEFAULT_FAST_MODEL
    if model in _CLAUDE_STRONG_MODELS:
        return DEFAULT_STRONG_MODEL
    return model


def _using_deepseek() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY"))


# ---------------------------------------------------------------------------
# Core request functions
# ---------------------------------------------------------------------------

def request_message(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
    cache_control: dict[str, Any] | None = None,
    thinking: dict[str, Any] | None = None,
):
    """Send a message to the Anthropic API. Returns response or None."""
    c = client()
    if not c:
        return None
    try:
        kwargs: dict[str, Any] = {
            "model": _normalize_model_for_provider(model),
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
        if thinking is not None:
            kwargs["thinking"] = thinking
        elif _using_deepseek():
            kwargs["thinking"] = {"type": "disabled"}
        return c.messages.create(**kwargs)
    except Exception:
        logger.exception("LLM message call failed")
        return None


def request_text(
    *, system: str, prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 512,
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
    *, system: str, prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 1024,
) -> dict | None:
    """Request JSON response from LLM. Returns parsed dict or None.

    Parsing goes through _json_parse_candidates() so truncated tails and
    trailing noise from the model don't drop otherwise valid payloads."""
    raw = request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    return _robust_json_loads(raw)


def request_structured_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str = DEFAULT_FAST_MODEL,
    max_tokens: int = 1024,
    fallback_model: str = CLAUDE_FALLBACK_MODEL,
    provider: str = "auto",
) -> StructuredJSONResult:
    """Request JSON with the best available structured-output path.

    DeepSeek's OpenAI-compatible surface supports `response_format=json_object`
    and performed better in local spikes for structured output. Claude remains
    a provider fallback when DeepSeek OpenAI-compatible fails or returns
    unparsable content.
    """
    if provider == "claude":
        return _request_claude_json(
            system=system,
            messages=messages,
            model=fallback_model,
            max_tokens=max_tokens,
        )
    deepseek_result: StructuredJSONResult | None = None
    if provider in {"auto", "deepseek_openai"} and os.getenv("DEEPSEEK_API_KEY"):
        deepseek_result = _request_deepseek_openai_json(
            system=system,
            messages=messages,
            model=_normalize_model_for_provider(model),
            max_tokens=max_tokens,
        )
        if deepseek_result.data is not None:
            return deepseek_result
    if provider == "deepseek_openai":
        return deepseek_result or StructuredJSONResult(data=None, provider="deepseek_openai", model=model, error="client_unavailable")

    if os.getenv("ANTHROPIC_API_KEY"):
        claude_result = _request_claude_json(
            system=system,
            messages=messages,
            model=fallback_model,
            max_tokens=max_tokens,
        )
        if deepseek_result is not None:
            return StructuredJSONResult(
                data=claude_result.data,
                provider=claude_result.provider,
                model=claude_result.model,
                raw_text=claude_result.raw_text,
                error=claude_result.error or deepseek_result.error,
                json_repair_used=claude_result.json_repair_used,
                provider_fallback_used=True,
            )
        return claude_result

    if deepseek_result is not None:
        return deepseek_result
    return StructuredJSONResult(
        data=None,
        provider="none",
        model=model,
        error="no_structured_json_provider_available",
    )


def classify_llm_exception(exc: BaseException) -> str:
    """Classify provider exceptions with stable operational labels."""
    try:
        import anthropic as _anthropic
    except Exception:
        _anthropic = None
    if _anthropic is not None:
        if isinstance(exc, _anthropic.APITimeoutError):
            return "timeout"
        if isinstance(exc, _anthropic.RateLimitError):
            return "rate_limit"
        if isinstance(exc, _anthropic.BadRequestError):
            return "bad_request"
        if isinstance(exc, _anthropic.AuthenticationError):
            return "auth"
        if isinstance(exc, _anthropic.APIConnectionError):
            return "connection"
        if isinstance(exc, _anthropic.APIError):
            return "api_other"
    if isinstance(exc, json.JSONDecodeError):
        return "json_parse"
    return "unknown"


def _request_deepseek_openai_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
) -> StructuredJSONResult:
    client_obj = deepseek_openai_client()
    if client_obj is None:
        return StructuredJSONResult(data=None, provider="deepseek_openai", model=model, error="client_unavailable")
    effective_max_tokens = max(max_tokens, DEEPSEEK_STRUCTURED_MIN_TOKENS)
    last_raw: str | None = None
    last_error: str | None = None
    for attempt in range(1, DEEPSEEK_STRUCTURED_ATTEMPTS + 1):
        try:
            response = client_obj.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=effective_max_tokens,
                response_format={"type": "json_object"},
                messages=_deepseek_json_messages(system=system, messages=messages, attempt=attempt),
            )
            raw = _openai_message_text(response)
            last_raw = raw
            data = _robust_json_loads(raw or "")
            if data is not None:
                return StructuredJSONResult(
                    data=data,
                    provider="deepseek_openai",
                    model=model,
                    raw_text=raw,
                    error=None,
                    json_repair_used=attempt > 1,
                )
            last_error = "json_parse_failed" if raw else "empty_response"
        except Exception as exc:
            logger.warning("deepseek_openai_structured_json_failed: %s", str(exc)[:200])
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            break
    return StructuredJSONResult(
        data=None,
        provider="deepseek_openai",
        model=model,
        raw_text=last_raw,
        error=last_error,
        json_repair_used=DEEPSEEK_STRUCTURED_ATTEMPTS > 1,
    )


def _deepseek_json_messages(*, system: str, messages: list[dict[str, Any]], attempt: int) -> list[dict[str, Any]]:
    """Wrap prompts for DeepSeek JSON mode according to provider guidance."""
    attempt_note = "" if attempt <= 1 else f"\nTentative {attempt}: la tentative precedente etait vide ou invalide. Corrige et retourne du JSON strict."
    json_contract = (
        "Tu dois repondre uniquement en JSON valide. Le mot JSON est volontairement explicite.\n"
        "Aucun markdown. Aucune prose hors JSON. Aucun champ vide si tu peux l'eviter.\n"
        "Si l'action n'est pas claire, utilise mutation_type=\"no_change\" avec rationale et fitmas_message non vides.\n"
        "Ne promets jamais une modification du plan si mutation_type=\"no_change\".\n"
        "fitmas_message doit etre une phrase complete, courte, sans coupure en fin de phrase.\n"
        "Exemple JSON attendu:\n"
        "{\n"
        '  "mutation_type": "no_change",\n'
        '  "target_session_id": null,\n'
        '  "second_session_id": null,\n'
        '  "target_date": null,\n'
        '  "rationale": "raison courte",\n'
        '  "fitmas_message": "message utilisateur court"\n'
        "}"
        f"{attempt_note}"
    )
    return [{"role": "system", "content": f"{system}\n\n{json_contract}"}, *messages]


def _request_claude_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
) -> StructuredJSONResult:
    client_obj = anthropic_client(provider="claude")
    if client_obj is None:
        return StructuredJSONResult(data=None, provider="claude_anthropic", model=model, error="client_unavailable")
    try:
        response = client_obj.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        raw = message_text(response)
        return StructuredJSONResult(
            data=_robust_json_loads(raw or ""),
            provider="claude_anthropic",
            model=model,
            raw_text=raw,
            error=None if raw else "empty_response",
        )
    except Exception as exc:
        logger.warning("claude_structured_json_failed: %s", str(exc)[:200])
        return StructuredJSONResult(
            data=None,
            provider="claude_anthropic",
            model=model,
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )


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


def _openai_message_text(response: Any) -> str | None:
    """Extract text from an OpenAI-compatible chat completion response."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    if message is None:
        return None
    content = getattr(message, "content", None)
    if content is None:
        return None
    text = str(content).strip()
    return text or None


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
    logger.warning("Failed to decode LLM JSON: %s", cleaned[:200])
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
        model=DEFAULT_FAST_MODEL,
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
