from __future__ import annotations

import logging
import os
from typing import Any, Callable

from fitmas.llm import gateway as gw


logger = logging.getLogger("fitmas.llm")


RequestMessageFn = Callable[..., Any | None]
RequestTextFn = Callable[..., str | None]
RequestJsonFn = Callable[..., dict | None]
GatewayStructuredJsonFn = Callable[..., Any]


def client():
    return gw.client()


def request_message(
    *,
    system: Any,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
    thinking: dict[str, Any] | None = None,
    output_config: dict[str, Any] | None = None,
):
    return gw.request_message(
        system=system,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        thinking=thinking,
        output_config=output_config,
    )


def request_text(
    *,
    system: str,
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 512,
    request_message_fn: RequestMessageFn = request_message,
) -> str | None:
    response = request_message_fn(
        system=system,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
    )
    return gw.message_text(response)


def request_json(
    *,
    system: str,
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
    request_text_fn: RequestTextFn = request_text,
) -> dict | None:
    raw = request_text_fn(
        system=system,
        prompt=prompt,
        model=model,
        max_tokens=max_tokens,
    )
    if not raw:
        return None
    return gw._robust_json_loads(raw)


def request_structured_json(
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 1024,
    schema_hint: str | None = None,
    request_json_fn: RequestJsonFn = request_json,
    default_request_json_fn: RequestJsonFn = request_json,
    request_message_fn: RequestMessageFn = request_message,
    default_request_message_fn: RequestMessageFn = request_message,
    request_text_fn: RequestTextFn = request_text,
    gateway_request_structured_json_fn: GatewayStructuredJsonFn = gw.request_structured_json,
    default_gateway_structured_json_fn: GatewayStructuredJsonFn = gw.request_structured_json,
) -> dict | None:
    gateway_is_patched = gateway_request_structured_json_fn is not default_gateway_structured_json_fn
    local_json_path_is_patched = (
        request_json_fn is not default_request_json_fn
        or request_message_fn is not default_request_message_fn
    )
    if (
        use_deepseek_openai_structured_output()
        and os.getenv("DEEPSEEK_API_KEY")
        and (gateway_is_patched or not local_json_path_is_patched)
    ):
        gateway_kwargs: dict[str, Any] = {
            "system": system,
            "messages": messages,
            "model": model,
            "max_tokens": max_tokens,
        }
        if schema_hint is not None:
            gateway_kwargs["schema_hint"] = schema_hint
        result = gateway_request_structured_json_fn(**gateway_kwargs)
        if result.provider_fallback_used:
            logger.info(
                "structured_json.provider_fallback provider=%s model=%s error=%s",
                result.provider,
                result.model,
                result.error,
            )
        return result.data
    if len(messages) == 1 and messages[0].get("role") == "user":
        return request_json_fn(
            system=system,
            prompt=str(messages[0].get("content") or ""),
            model=model,
            max_tokens=max_tokens,
        )
    raw = request_text_fn(
        system=system,
        prompt="\n\n".join(str(message.get("content") or "") for message in messages if message.get("role") == "user"),
        model=model,
        max_tokens=max_tokens,
    )
    return gw._robust_json_loads(raw or "") if raw else None


def use_deepseek_openai_structured_output() -> bool:
    raw = os.getenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def deepseek_tool_thinking_kwargs() -> dict[str, dict[str, str]]:
    if not os.getenv("DEEPSEEK_API_KEY"):
        return {}
    raw_enabled = str(os.getenv("FITMAS_DEEPSEEK_TOOL_THINKING") or "").strip().lower()
    if raw_enabled not in {"1", "true", "yes", "on", "enabled"}:
        return {}
    effort = str(os.getenv("FITMAS_DEEPSEEK_TOOL_THINKING_EFFORT") or "high").strip().lower()
    if effort not in {"high", "max"}:
        effort = "high"
    return {
        "thinking": {"type": "enabled"},
        "output_config": {"effort": effort},
    }


def classify_llm_exception(exc: BaseException) -> str:
    return gw.classify_llm_exception(exc)
