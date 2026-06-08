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
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_OPENAI_BASE_URL = "https://api.deepseek.com"
MISTRAL_OPENAI_BASE_URL = "https://api.mistral.ai/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROK_OPENAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_FAST_MODEL = "deepseek-v4-flash"
DEFAULT_STRONG_MODEL = "deepseek-v4-pro"
DEFAULT_MODEL = DEFAULT_STRONG_MODEL
DEFAULT_MISTRAL_MODEL = "mistral-small-2603"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_GROK_MODEL = "grok-4.3"
DEFAULT_MISTRAL_REASONING_EFFORT = "high"
DEFAULT_GEMINI_REASONING_EFFORT = "medium"
DEFAULT_GROK_REASONING_EFFORT = "low"
_CLAUDE_FAST_MODELS = {"claude-haiku-4-5-20251001"}
_CLAUDE_STRONG_MODELS = {"claude-sonnet-4-6"}
CLAUDE_FALLBACK_MODEL = "claude-haiku-4-5-20251001"
DEEPSEEK_STRUCTURED_MIN_TOKENS = 3072
DEEPSEEK_STRUCTURED_ATTEMPTS = 3


@dataclass(frozen=True)
class StructuredJSONResult:
    data: dict | None
    provider: str
    model: str
    raw_text: str | None = None
    error: str | None = None
    json_repair_used: bool = False
    provider_fallback_used: bool = False


@dataclass(frozen=True)
class HeartbeatTextGeneration:
    raw_text: str | None
    text: str | None
    reason: str
    allow_no_send: bool


@dataclass(frozen=True)
class LLMProviderProfile:
    name: str
    api_key_env: str
    base_url: str
    model: str
    api_style: str = "openai"
    reasoning_effort: str | None = None
    api_key_env_aliases: tuple[str, ...] = ()


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


def active_llm_profile(profile_name: str | None = None) -> LLMProviderProfile:
    """Return the active provider profile for smoke/model comparisons.

    Default runtime behavior stays DeepSeek-first. Explicit FITMAS_LLM_PROFILE
    pins the provider so smoke comparisons do not silently fall through to a
    different model family.
    """
    raw = (profile_name or os.getenv("FITMAS_LLM_PROFILE") or "").strip().lower()
    aliases = {
        "": "deepseek" if os.getenv("DEEPSEEK_API_KEY") or not os.getenv("ANTHROPIC_API_KEY") else "claude",
        "auto": "deepseek" if os.getenv("DEEPSEEK_API_KEY") or not os.getenv("ANTHROPIC_API_KEY") else "claude",
        "xai": "grok",
        "grok4": "grok",
    }
    name = aliases.get(raw, raw)
    generic_model = os.getenv("FITMAS_LLM_MODEL")
    if name == "claude":
        return LLMProviderProfile(
            name="claude",
            api_key_env="ANTHROPIC_API_KEY",
            base_url="",
            model=generic_model or os.getenv("FITMAS_CLAUDE_MODEL") or CLAUDE_FALLBACK_MODEL,
            api_style="anthropic",
        )
    if name == "mistral":
        return LLMProviderProfile(
            name="mistral",
            api_key_env="MISTRAL_API_KEY",
            base_url=os.getenv("FITMAS_MISTRAL_BASE_URL") or MISTRAL_OPENAI_BASE_URL,
            model=generic_model or os.getenv("FITMAS_MISTRAL_MODEL") or DEFAULT_MISTRAL_MODEL,
            reasoning_effort=_reasoning_effort_for_profile("mistral", DEFAULT_MISTRAL_REASONING_EFFORT),
        )
    if name == "gemini":
        return LLMProviderProfile(
            name="gemini",
            api_key_env="GEMINI_API_KEY",
            base_url=os.getenv("FITMAS_GEMINI_BASE_URL") or GEMINI_OPENAI_BASE_URL,
            model=generic_model or os.getenv("FITMAS_GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
            reasoning_effort=_reasoning_effort_for_profile("gemini", DEFAULT_GEMINI_REASONING_EFFORT),
        )
    if name == "grok":
        return LLMProviderProfile(
            name="grok",
            api_key_env="XAI_API_KEY",
            base_url=os.getenv("FITMAS_GROK_BASE_URL") or GROK_OPENAI_BASE_URL,
            model=generic_model or os.getenv("FITMAS_GROK_MODEL") or DEFAULT_GROK_MODEL,
            reasoning_effort=_reasoning_effort_for_profile("grok", DEFAULT_GROK_REASONING_EFFORT),
            api_key_env_aliases=("GROK_API_KEY",),
        )
    return LLMProviderProfile(
        name="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url=os.getenv("FITMAS_DEEPSEEK_BASE_URL") or DEEPSEEK_OPENAI_BASE_URL,
        model=generic_model or os.getenv("FITMAS_DEEPSEEK_MODEL") or DEFAULT_STRONG_MODEL,
    )


def _reasoning_effort_for_profile(profile_name: str, default: str | None) -> str | None:
    raw = (
        os.getenv(f"FITMAS_{profile_name.upper()}_REASONING_EFFORT")
        or os.getenv("FITMAS_LLM_REASONING_EFFORT")
        or default
    )
    normalized = str(raw or "").strip().lower()
    return normalized or None


def _explicit_llm_profile() -> bool:
    return bool(str(os.getenv("FITMAS_LLM_PROFILE") or "").strip())


def _profile_uses_openai_chat(profile: LLMProviderProfile) -> bool:
    return profile.api_style == "openai" and profile.name in {"mistral", "gemini", "grok"}


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
    return openai_compatible_client(active_llm_profile("deepseek"))


def openai_compatible_client(profile: LLMProviderProfile | None = None):
    """Return an OpenAI-compatible client for the selected profile or None."""
    selected = profile or active_llm_profile()
    api_key = _api_key_for_profile(selected)
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    return OpenAI(api_key=api_key, base_url=selected.base_url)


def _api_key_for_profile(profile: LLMProviderProfile) -> str | None:
    for env_name in (profile.api_key_env, *profile.api_key_env_aliases):
        value = os.getenv(env_name)
        if value:
            return value
    return None


def _normalize_model_for_provider(model: str) -> str:
    """Map legacy Claude model names to current DeepSeek V4 equivalents."""
    if not os.getenv("DEEPSEEK_API_KEY"):
        return model
    if model in _CLAUDE_FAST_MODELS:
        return DEFAULT_FAST_MODEL
    if model in _CLAUDE_STRONG_MODELS:
        return DEFAULT_STRONG_MODEL
    return model


def _effective_model_for_profile(model: str, profile: LLMProviderProfile) -> str:
    if profile.name == "deepseek":
        if model == DEFAULT_MODEL:
            return profile.model
        return _normalize_model_for_provider(model)
    if profile.name == "claude":
        return model if model not in {DEFAULT_FAST_MODEL, DEFAULT_STRONG_MODEL, DEFAULT_MODEL} else profile.model
    return profile.model


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
    output_config: dict[str, Any] | None = None,
):
    """Send a message to the Anthropic API. Returns response or None."""
    profile = active_llm_profile()
    if _profile_uses_openai_chat(profile):
        return _request_openai_compatible_message(
            profile=profile,
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
    if _explicit_llm_profile() and profile.name in {"deepseek", "claude"}:
        c = anthropic_client(provider=profile.name)
    else:
        c = client()
    if not c:
        return None
    anthropic_profile = profile if profile.name in {"deepseek", "claude"} else active_llm_profile("deepseek")
    try:
        kwargs: dict[str, Any] = {
            "model": _effective_model_for_profile(model, anthropic_profile),
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
        elif anthropic_profile.name == "deepseek" and _using_deepseek():
            kwargs["thinking"] = {"type": "disabled"}
        if output_config is not None:
            kwargs["output_config"] = output_config
        return c.messages.create(**kwargs)
    except Exception:
        logger.exception("LLM message call failed")
        return None


def _request_openai_compatible_message(
    *,
    profile: LLMProviderProfile,
    system: Any,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
):
    client_obj = openai_compatible_client(profile)
    if client_obj is None:
        return None
    try:
        chat_messages = _openai_chat_messages(system=system, messages=messages)
        kwargs: dict[str, Any] = {
            "model": _effective_model_for_profile(model, profile),
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": chat_messages,
        }
        openai_tools = _openai_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools
        openai_tool_choice = _openai_tool_choice(tool_choice)
        if openai_tool_choice is not None:
            kwargs["tool_choice"] = openai_tool_choice
        _apply_openai_compatible_provider_params(kwargs, profile)
        response = client_obj.chat.completions.create(**kwargs)
        return _as_anthropic_compatible_response(response)
    except Exception:
        logger.exception("%s_openai_message_call_failed", profile.name)
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


_DEFAULT_REQUEST_TEXT = request_text


def request_json(
    *,
    system: Any,
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    schema_hint: str | None = None,
) -> dict | None:
    """Request JSON response from LLM. Returns parsed dict or None.

    Parsing goes through _json_parse_candidates() so truncated tails and
    trailing noise from the model don't drop otherwise valid payloads."""
    profile = active_llm_profile()
    if profile.api_style == "openai" and request_text is _DEFAULT_REQUEST_TEXT:
        result = request_structured_json(
            system=system,
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
        )
        if result.data is not None:
            return result.data
    raw = request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    return _robust_json_loads(
        raw,
        normalize_decision_payload=_should_normalize_decision_payload(schema_hint),
    )


def request_structured_json(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str = DEFAULT_FAST_MODEL,
    max_tokens: int = 1024,
    fallback_model: str = CLAUDE_FALLBACK_MODEL,
    provider: str = "auto",
    schema_hint: str | None = None,
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
            schema_hint=schema_hint,
        )
    if provider in {"mistral", "gemini", "grok"}:
        return _request_openai_compatible_json(
            profile=active_llm_profile(provider),
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
        )

    active_profile = active_llm_profile()
    if provider == "auto" and active_profile.name in {"mistral", "gemini", "grok"}:
        return _request_openai_compatible_json(
            profile=active_profile,
            system=system,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
        )
    if provider == "auto" and active_profile.name == "claude":
        return _request_claude_json(
            system=system,
            messages=messages,
            model=active_profile.model,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
        )

    deepseek_result: StructuredJSONResult | None = None
    if provider in {"auto", "deepseek_openai"} and os.getenv("DEEPSEEK_API_KEY"):
        deepseek_result = _request_deepseek_openai_json(
            system=system,
            messages=messages,
            model=_normalize_model_for_provider(model),
            max_tokens=max_tokens,
            schema_hint=schema_hint,
        )
        if deepseek_result.data is not None:
            return deepseek_result
    if _explicit_llm_profile() and active_profile.name == "deepseek":
        return deepseek_result or StructuredJSONResult(data=None, provider="deepseek_openai", model=model, error="client_unavailable")
    if provider == "deepseek_openai":
        return deepseek_result or StructuredJSONResult(data=None, provider="deepseek_openai", model=model, error="client_unavailable")

    if os.getenv("ANTHROPIC_API_KEY"):
        claude_result = _request_claude_json(
            system=system,
            messages=messages,
            model=fallback_model,
            max_tokens=max_tokens,
            schema_hint=schema_hint,
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
    system: Any,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    schema_hint: str | None = None,
) -> StructuredJSONResult:
    return _request_openai_compatible_json(
        profile=active_llm_profile("deepseek"),
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        schema_hint=schema_hint,
        provider_label="deepseek_openai",
    )


def _request_openai_compatible_json(
    *,
    profile: LLMProviderProfile,
    system: Any,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    schema_hint: str | None = None,
    provider_label: str | None = None,
) -> StructuredJSONResult:
    client_obj = openai_compatible_client(profile)
    label = provider_label or f"{profile.name}_openai"
    if client_obj is None:
        return StructuredJSONResult(data=None, provider=label, model=_effective_model_for_profile(model, profile), error="client_unavailable")
    effective_max_tokens = max(max_tokens, DEEPSEEK_STRUCTURED_MIN_TOKENS)
    last_raw: str | None = None
    last_error: str | None = None
    for attempt in range(1, DEEPSEEK_STRUCTURED_ATTEMPTS + 1):
        try:
            response = client_obj.chat.completions.create(
                model=_effective_model_for_profile(model, profile),
                temperature=0,
                max_tokens=effective_max_tokens,
                response_format={"type": "json_object"},
                messages=_openai_json_messages(
                    system=system,
                    messages=messages,
                    attempt=attempt,
                    schema_hint=schema_hint,
                ),
                **_openai_compatible_provider_params(profile),
            )
            raw = _openai_message_text(response)
            last_raw = raw
            data = _robust_json_loads(
                raw or "",
                normalize_decision_payload=_should_normalize_decision_payload(schema_hint),
            )
            if data is not None:
                return StructuredJSONResult(
                    data=data,
                    provider=label,
                    model=_effective_model_for_profile(model, profile),
                    raw_text=raw,
                    error=None,
                    json_repair_used=attempt > 1,
                )
            last_error = "json_parse_failed" if raw else "empty_response"
        except Exception as exc:
            logger.warning("%s_structured_json_failed: %s", label, str(exc)[:200])
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            break
    return StructuredJSONResult(
        data=None,
        provider=label,
        model=_effective_model_for_profile(model, profile),
        raw_text=last_raw,
        error=last_error,
        json_repair_used=DEEPSEEK_STRUCTURED_ATTEMPTS > 1,
    )


def render_system_text(system: Any) -> str:
    """Render Anthropic-style system blocks into plain provider text."""
    if system is None:
        return ""
    if isinstance(system, str):
        return system.strip()
    if isinstance(system, dict):
        text = system.get("text")
        return str(text).strip() if text is not None else str(system).strip()
    if isinstance(system, list):
        parts: list[str] = []
        for item in system:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if text is not None and str(text).strip():
                parts.append(str(text).strip())
        return "\n\n".join(parts)
    return str(system).strip()


def _structured_json_contract(*, schema_hint: str | None = None, attempt: int | None = None) -> str:
    lines = [
        "Tu dois repondre uniquement en JSON valide. Le mot JSON est volontairement explicite.",
        "Aucun markdown. Aucune prose hors JSON.",
        "Respecte exactement le schema demande dans le prompt et le system prompt.",
        "N'ajoute pas de champ legacy absent du schema demande.",
    ]
    if schema_hint:
        lines.extend(["Schema attendu:", schema_hint.strip()])
    if attempt is not None and attempt > 1:
        lines.append(
            f"Tentative {attempt}: la tentative precedente etait vide ou invalide. Corrige et retourne du JSON strict."
        )
    return "\n".join(line for line in lines if line)


def _deepseek_json_messages(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    attempt: int,
    schema_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Wrap prompts for DeepSeek JSON mode according to provider guidance."""
    return _openai_json_messages(
        system=system,
        messages=messages,
        attempt=attempt,
        schema_hint=schema_hint,
    )


def _openai_json_messages(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    attempt: int,
    schema_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Wrap prompts for OpenAI-compatible JSON mode."""
    system_text = render_system_text(system)
    json_contract = _structured_json_contract(schema_hint=schema_hint, attempt=attempt)
    content = "\n\n".join(part for part in (system_text, json_contract) if part.strip())
    return [{"role": "system", "content": content}, *messages]


def _openai_chat_messages(*, system: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    system_text = render_system_text(system)
    converted: list[dict[str, Any]] = []
    if system_text:
        converted.append({"role": "system", "content": system_text})
    for message in messages:
        converted.extend(_openai_messages_from_anthropic_message(message))
    return converted


def _openai_messages_from_anthropic_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    role = str(message.get("role") or "user")
    content = message.get("content")
    if isinstance(content, list):
        if role == "assistant":
            return [_openai_assistant_message_from_blocks(content)]
        if role == "user":
            return _openai_user_messages_from_blocks(content)
    return [{"role": role, "content": "" if content is None else str(content)}]


def _openai_assistant_message_from_blocks(blocks: list[Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in blocks:
        block_type = _block_value(block, "type")
        if block_type == "text":
            text = str(_block_value(block, "text") or "").strip()
            if text:
                text_parts.append(text)
        elif block_type == "tool_use":
            name = str(_block_value(block, "name") or "")
            if not name:
                continue
            tool_calls.append(
                {
                    "id": str(_block_value(block, "id") or ""),
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(_block_value(block, "input") or {}, ensure_ascii=False),
                    },
                }
            )
    message: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _openai_user_messages_from_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    text_parts: list[str] = []

    def flush_text() -> None:
        if not text_parts:
            return
        messages.append({"role": "user", "content": "\n".join(text_parts)})
        text_parts.clear()

    for block in blocks:
        block_type = _block_value(block, "type")
        if block_type == "text":
            text = str(_block_value(block, "text") or "").strip()
            if text:
                text_parts.append(text)
            continue
        if block_type == "tool_result":
            flush_text()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": str(_block_value(block, "tool_use_id") or ""),
                    "content": str(_block_value(block, "content") or ""),
                }
            )
    flush_text()
    return messages or [{"role": "user", "content": ""}]


def _openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        if not name:
            continue
        parameters = dict(tool.get("input_schema") or {})
        if not parameters:
            parameters = {"type": "object", "properties": {}}
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "parameters": parameters,
                },
            }
        )
    return converted or None


def _openai_tool_choice(tool_choice: dict[str, Any] | None) -> Any | None:
    if not tool_choice:
        return None
    choice_type = str(tool_choice.get("type") or "")
    if choice_type in {"auto", "none", "required"}:
        return choice_type
    if choice_type == "any":
        return "required"
    if choice_type == "tool":
        name = str(tool_choice.get("name") or "")
        if name:
            return {"type": "function", "function": {"name": name}}
    return "auto"


def _openai_compatible_provider_params(profile: LLMProviderProfile) -> dict[str, Any]:
    if not profile.reasoning_effort:
        return {}
    return {"reasoning_effort": profile.reasoning_effort}


def _apply_openai_compatible_provider_params(kwargs: dict[str, Any], profile: LLMProviderProfile) -> None:
    kwargs.update(_openai_compatible_provider_params(profile))


def _as_anthropic_compatible_response(response: Any) -> Any:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return SimpleNamespace(content=[], stop_reason="end_turn", raw_response=response)
    choice = choices[0]
    message = getattr(choice, "message", None)
    content_blocks: list[Any] = []
    if message is not None:
        text = _openai_content_text(getattr(message, "content", None))
        if text:
            content_blocks.append(SimpleNamespace(type="text", text=text))
        for tool_call in getattr(message, "tool_calls", None) or []:
            function = getattr(tool_call, "function", None)
            name = str(getattr(function, "name", "") or "")
            if not name:
                continue
            content_blocks.append(
                SimpleNamespace(
                    type="tool_use",
                    id=str(getattr(tool_call, "id", "") or ""),
                    name=name,
                    input=_json_object_or_raw(getattr(function, "arguments", "") or ""),
                )
            )
    finish_reason = str(getattr(choice, "finish_reason", "") or "")
    stop_reason = "tool_use" if any(getattr(block, "type", None) == "tool_use" for block in content_blocks) else finish_reason
    return SimpleNamespace(
        content=content_blocks,
        stop_reason=stop_reason or "end_turn",
        raw_response=response,
    )


def _json_object_or_raw(raw: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw or "{}")
    except Exception:
        return {"_raw_arguments": raw}
    if isinstance(loaded, dict):
        return loaded
    return {"_raw_arguments": raw}


def _openai_content_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            item_type = _block_value(item, "type")
            if item_type not in {"text", "output_text"}:
                continue
            text = str(_block_value(item, "text") or "").strip()
            if text:
                texts.append(text)
        return "\n".join(texts).strip() or None
    text = str(content).strip()
    return text or None


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _request_claude_json(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str,
    max_tokens: int,
    schema_hint: str | None = None,
) -> StructuredJSONResult:
    client_obj = anthropic_client(provider="claude")
    if client_obj is None:
        return StructuredJSONResult(data=None, provider="claude_anthropic", model=model, error="client_unavailable")
    try:
        response = client_obj.messages.create(
            model=model,
            max_tokens=max_tokens,
            system="\n\n".join(
                part
                for part in (
                    render_system_text(system),
                    _structured_json_contract(schema_hint=schema_hint),
                )
                if part.strip()
            ),
            messages=messages,
        )
        raw = message_text(response)
        return StructuredJSONResult(
            data=_robust_json_loads(
                raw or "",
                normalize_decision_payload=_should_normalize_decision_payload(schema_hint),
            ),
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
    openai_text = _openai_message_text(response)
    if openai_text:
        return openai_text
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
    return _openai_content_text(getattr(message, "content", None))


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
        elif block_type == "thinking":
            item = {
                "type": "thinking",
                "thinking": getattr(block, "thinking", getattr(block, "text", "")),
            }
            signature = getattr(block, "signature", None)
            if signature:
                item["signature"] = signature
            serialized.append(item)
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

def _robust_json_loads(raw: str, *, normalize_decision_payload: bool = True) -> dict | None:
    """Parse a (possibly messy) LLM string into a dict.

    Tries a small cascade of candidate repairs so trailing prose,
    truncated tails, or leading noise don't drop valid JSON payloads.
    Returns the first candidate that parses to a dict, else None."""
    cleaned = _strip_json_fences(raw)
    if cleaned.lstrip().startswith("_type"):
        repaired = _repair_deepseek_pseudo_json(cleaned)
        if repaired is not None:
            return repaired
    for candidate in _json_parse_candidates(cleaned):
        try:
            loaded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return _normalize_parsed_decision_payload(loaded) if normalize_decision_payload else loaded
    repaired = _repair_deepseek_pseudo_json(cleaned)
    if repaired is not None:
        return repaired
    logger.warning("Failed to decode LLM JSON: %s", cleaned[:200])
    return None


def _should_normalize_decision_payload(schema_hint: str | None) -> bool:
    hint = str(schema_hint or "").strip().lower()
    if not hint:
        return True
    if "adaptationproposal" in hint or "adaptation_proposal" in hint:
        return False
    return True


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


def _repair_deepseek_pseudo_json(raw: str) -> dict | None:
    """Repair DeepSeek's common `_type: value` pseudo-JSON into a dict.

    This is syntax repair only. It copies explicit fields and normalizes
    `_type` into the existing FitMAS response contract; it does not infer
    intent from the user text.
    """
    text = raw.strip()
    if "_type" not in text and "mutation_type" not in text:
        return None
    prefixed_type = _extract_prefixed_type(text)
    if "=" in text and (":" not in text.splitlines()[0]):
        data = _parse_inline_key_values(text)
    else:
        data = _parse_yamlish_key_values(text)
    if prefixed_type:
        data["_type"] = prefixed_type
    embedded_plan_patch = _extract_embedded_plan_patch(text)
    if embedded_plan_patch is not None:
        data["plan_patch"] = embedded_plan_patch
        if isinstance(embedded_plan_patch.get("operations"), list):
            data["operations"] = embedded_plan_patch["operations"]
    embedded_mutation_decision = _extract_embedded_mutation_decision(text)
    if embedded_mutation_decision is not None:
        data["mutation_decision"] = embedded_mutation_decision
    if not data:
        return None
    return _normalize_repaired_decision_payload(data)


def _parse_inline_key_values(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    chunks: list[str] = []
    for line in text.splitlines():
        chunks.extend(_split_top_level_commas(line))
    for chunk in chunks:
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip()
        if not key:
            continue
        data[key] = _coerce_pseudo_json_scalar(value)
    return data


def _extract_prefixed_type(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("_type"):
        return None
    separator = "=" if stripped.startswith("_type=") else ":" if stripped.startswith("_type:") else None
    if separator is None:
        return None
    remainder = stripped.split(separator, 1)[1].strip()
    if not remainder:
        return None
    return _normalize_response_type_token(remainder.split(maxsplit=1)[0])


def _split_top_level_commas(text: str) -> list[str]:
    chunks: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    escape = False
    for char in text:
        if escape:
            buffer.append(char)
            escape = False
            continue
        if char == "\\" and quote:
            buffer.append(char)
            escape = True
            continue
        if char in {"'", '"'}:
            buffer.append(char)
            quote = None if quote == char else char if quote is None else quote
            continue
        if char == "," and quote is None:
            chunks.append("".join(buffer).strip())
            buffer = []
            continue
        buffer.append(char)
    if buffer:
        chunks.append("".join(buffer).strip())
    return chunks


def _parse_yamlish_key_values(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    operations: list[dict[str, Any]] = []
    current_operation: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped in {"plan_patch:", "operations:"}:
            continue
        if stripped.startswith("- "):
            current_operation = {}
            operations.append(current_operation)
            remainder = stripped[2:].strip()
            if ":" in remainder:
                key, value = remainder.split(":", 1)
                current_operation[key.strip()] = _coerce_pseudo_json_scalar(value)
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if line.startswith(" ") and current_operation is not None:
            current_operation[key] = _coerce_pseudo_json_scalar(value)
        elif key not in {"plan_patch", "operations"}:
            data[key] = _coerce_pseudo_json_scalar(value)
    if operations:
        data["operations"] = operations
    return data


def _extract_embedded_plan_patch(text: str) -> dict[str, Any] | None:
    return _extract_embedded_object(text, field_name="plan_patch")


def _extract_embedded_mutation_decision(text: str) -> dict[str, Any] | None:
    return _extract_embedded_object(text, field_name="mutation_decision")


def _extract_embedded_object(text: str, *, field_name: str) -> dict[str, Any] | None:
    colon_marker = f"{field_name}:"
    equals_marker = f"{field_name}="
    marker_index = text.find(colon_marker)
    marker_length = len(colon_marker)
    if marker_index < 0:
        marker_index = text.find(equals_marker)
        marker_length = len(equals_marker)
    if marker_index < 0:
        return None
    raw_json = text[marker_index + marker_length:].strip()
    if not raw_json.startswith("{"):
        return None
    for candidate in _json_parse_candidates(raw_json):
        try:
            loaded = json.loads(candidate)
        except Exception:
            continue
        if isinstance(loaded, dict):
            return loaded
    return None


def _coerce_pseudo_json_scalar(value: Any) -> Any:
    raw = str(value).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    lowered = raw.lower()
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if raw.isdigit():
        return int(raw)
    return raw


def _normalize_repaired_decision_payload(data: dict[str, Any]) -> dict | None:
    payload = _normalize_parsed_decision_payload(data)
    if payload is None:
        return None
    raw_type = str(payload.get("response_type") or payload.get("mutation_type") or "").strip()
    if not payload.get("mutation_type") and not raw_type:
        return None
    return payload


def _normalize_parsed_decision_payload(data: dict[str, Any]) -> dict:
    payload = dict(data)
    explicit_type = payload.pop("_type", None)
    response_type = payload.get("response_type")
    raw_type = _normalize_response_type_token(explicit_type if explicit_type is not None else response_type or payload.get("mutation_type") or "")
    if not raw_type and "plan_patch" not in payload:
        return payload
    if raw_type and (explicit_type is not None or response_type is not None):
        payload["response_type"] = raw_type
    operations = payload.pop("operations", None)
    existing_plan_patch = payload.get("plan_patch") if isinstance(payload.get("plan_patch"), dict) else None
    if operations is None and existing_plan_patch is not None:
        operations = existing_plan_patch.get("operations")
    if raw_type in {"reply", "no_change", "requires_confirmation"}:
        payload.setdefault("mutation_type", "no_change")
    elif raw_type == "mutation_decision" and isinstance(payload.get("mutation_decision"), dict):
        mutation = payload["mutation_decision"]
        payload.setdefault("mutation_type", mutation.get("mutation_type"))
        for key, value in mutation.items():
            payload.setdefault(key, value)
    elif raw_type == "plan_patch":
        operation_list = [op for op in (operations or []) if isinstance(op, dict)]
        if operation_list:
            first_operation = operation_list[0]
            payload.setdefault("mutation_type", first_operation.get("operation_type"))
            for key, value in first_operation.items():
                if key != "operation_type":
                    payload.setdefault(key, value)
            payload["plan_patch"] = {
                "coach_message": str((existing_plan_patch or {}).get("coach_message") or payload.get("fitmas_message") or ""),
                "operations": operation_list,
            }
        else:
            payload.setdefault("mutation_type", "no_change")
    elif raw_type:
        payload.setdefault("mutation_type", raw_type)
    if not payload.get("mutation_type"):
        return None
    payload.setdefault("rationale", "")
    payload.setdefault("fitmas_message", "")
    return payload


def _normalize_response_type_token(raw: Any) -> str:
    value = str(raw or "").strip().strip('"').strip("'")
    known_types = (
        "plan_patch",
        "mutation_decision",
        "requires_confirmation",
        "no_change",
        "reply",
        "move_session",
        "lighten_day",
        "swap_sessions",
        "update_session",
        "replace_session",
        "create_session",
    )
    for known_type in known_types:
        if known_type in value:
            return known_type
    return value


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


def generate_heartbeat_text_with_debug(
    system: str,
    prompt: str,
    *,
    allow_no_send: bool = True,
) -> HeartbeatTextGeneration:
    """Generate heartbeat text and expose raw/normalized decisions for debug dumps."""
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
        return HeartbeatTextGeneration(
            raw_text=None,
            text=None,
            reason="llm_unavailable",
            allow_no_send=allow_no_send,
        )

    text = message_text(response)
    if not text:
        return HeartbeatTextGeneration(
            raw_text=None,
            text=None,
            reason="empty_response",
            allow_no_send=allow_no_send,
        )

    # Check for NO_SEND token (exact match or wrapped in markup)
    raw_text = text
    cleaned = text.replace("*", "").replace("`", "").replace("#", "").strip()
    if cleaned.upper() == NO_SEND_TOKEN:
        logger.info("LLM opted out with NO_SEND")
        return HeartbeatTextGeneration(
            raw_text=raw_text,
            text=None,
            reason="no_send_token",
            allow_no_send=allow_no_send,
        )

    # NO_SEND + short ack (<100 chars) -> also suppress
    if NO_SEND_TOKEN in text.upper() and len(text) < 100:
        logger.info("LLM opted out with NO_SEND + short ack")
        return HeartbeatTextGeneration(
            raw_text=raw_text,
            text=None,
            reason="no_send_short_ack",
            allow_no_send=allow_no_send,
        )

    # NO_SEND + real content -> strip token, deliver content
    if NO_SEND_TOKEN in text.upper():
        text = text.replace(NO_SEND_TOKEN, "").replace("no_send", "").strip()
        if not text:
            return HeartbeatTextGeneration(
                raw_text=raw_text,
                text=None,
                reason="no_send_after_strip",
                allow_no_send=allow_no_send,
            )

    return HeartbeatTextGeneration(
        raw_text=raw_text,
        text=text,
        reason="generated",
        allow_no_send=allow_no_send,
    )


def generate_heartbeat_text(system: str, prompt: str, *, allow_no_send: bool = True) -> str | None:
    """Generate text for heartbeat messages. Returns None on failure or NO_SEND."""
    return generate_heartbeat_text_with_debug(
        system,
        prompt,
        allow_no_send=allow_no_send,
    ).text
