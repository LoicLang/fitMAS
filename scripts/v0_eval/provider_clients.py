from __future__ import annotations

from dataclasses import dataclass
import json
import os
import random
import time
from typing import Any

from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall, ToolSchema


_MAX_RETRIES = int(os.getenv("FITMAS_V0_LLM_MAX_RETRIES") or "6")
_RETRY_BASE_DELAY = float(os.getenv("FITMAS_V0_LLM_RETRY_BASE_DELAY") or "2.0")
_RETRY_MAX_DELAY = float(os.getenv("FITMAS_V0_LLM_RETRY_MAX_DELAY") or "60.0")
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] | None = None


def _transient_errors() -> tuple[type[BaseException], ...]:
    global _TRANSIENT_ERRORS
    if _TRANSIENT_ERRORS is None:
        from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

        _TRANSIENT_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
    return _TRANSIENT_ERRORS


def _retry_after_seconds(exc: Any) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return 0.0
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    api_key_env: str
    model: str
    base_url: str = ""
    style: str = "openai"
    reasoning_effort: str | None = None
    api_key_env_aliases: tuple[str, ...] = ()


class ProviderConfigError(RuntimeError):
    pass


class MeteredLLMClient:
    def __init__(self, client: Any, provider: str, model: str):
        self.client = client
        self.provider = provider
        self.model = model
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self._retry_wait_baseline = float(getattr(client, "total_retry_wait_s", 0.0))

    @property
    def retry_wait_s(self) -> float:
        return float(getattr(self.client, "total_retry_wait_s", 0.0)) - self._retry_wait_baseline

    def chat_with_tools(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSchema]) -> LLMResponse:
        response = self.client.chat_with_tools(system, messages, tools)
        self.calls += 1
        self.tokens_in += response.tokens_in
        self.tokens_out += response.tokens_out
        return response


def provider_profile(name: str) -> ProviderProfile:
    if name == "deepseek":
        return ProviderProfile(
            name="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            model=os.getenv("FITMAS_V0_DEEPSEEK_MODEL") or os.getenv("FITMAS_DEEPSEEK_MODEL") or "deepseek-v4-pro",
            base_url=os.getenv("FITMAS_V0_DEEPSEEK_BASE_URL") or os.getenv("FITMAS_DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        )
    if name == "gemini":
        return ProviderProfile(
            name="gemini",
            api_key_env="GEMINI_API_KEY",
            model=os.getenv("FITMAS_V0_GEMINI_MODEL") or os.getenv("FITMAS_GEMINI_MODEL") or "gemini-3.5-flash",
            base_url=os.getenv("FITMAS_V0_GEMINI_BASE_URL") or os.getenv("FITMAS_GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta/openai/",
            reasoning_effort=os.getenv("FITMAS_V0_GEMINI_REASONING_EFFORT") or os.getenv("FITMAS_GEMINI_REASONING_EFFORT") or "medium",
        )
    if name == "grok":
        return ProviderProfile(
            name="grok",
            api_key_env="XAI_API_KEY",
            model=os.getenv("FITMAS_V0_GROK_MODEL") or os.getenv("FITMAS_GROK_MODEL") or "grok-4.3",
            base_url=os.getenv("FITMAS_V0_GROK_BASE_URL") or os.getenv("FITMAS_GROK_BASE_URL") or "https://api.x.ai/v1",
            reasoning_effort=os.getenv("FITMAS_V0_GROK_REASONING_EFFORT") or os.getenv("FITMAS_GROK_REASONING_EFFORT") or "low",
            api_key_env_aliases=("GROK_API_KEY",),
        )
    if name == "mistral":
        return ProviderProfile(
            name="mistral",
            api_key_env="MISTRAL_API_KEY",
            model=os.getenv("FITMAS_V0_MISTRAL_MODEL") or os.getenv("FITMAS_MISTRAL_MODEL") or "mistral-medium-2604",
            base_url=os.getenv("FITMAS_V0_MISTRAL_BASE_URL") or os.getenv("FITMAS_MISTRAL_BASE_URL") or "https://api.mistral.ai/v1",
            reasoning_effort=os.getenv("FITMAS_V0_MISTRAL_REASONING_EFFORT") or os.getenv("FITMAS_MISTRAL_REASONING_EFFORT") or "high",
        )
    raise ProviderConfigError(f"unknown_provider:{name}")


def build_provider_client(name: str):
    profile = provider_profile(name)
    api_key = next((os.getenv(env_name) for env_name in (profile.api_key_env, *profile.api_key_env_aliases) if os.getenv(env_name)), None)
    if not api_key:
        raise ProviderConfigError(f"missing_env:{profile.api_key_env}")
    from openai import OpenAI

    return OpenAICompatibleToolClient(profile, OpenAI(api_key=api_key, base_url=profile.base_url, max_retries=0))


class OpenAICompatibleToolClient:
    def __init__(self, profile: ProviderProfile, client: Any):
        self.profile = profile
        self.client = client
        self.total_retry_wait_s = 0.0

    def chat_with_tools(self, system: str, messages: list[dict[str, Any]], tools: list[ToolSchema]) -> LLMResponse:
        context, provider_messages = _provider_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.profile.model,
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 1024,
            "messages": [{"role": "system", "content": _join(system, context)}, *provider_messages],
        }
        if tools:
            kwargs["tools"] = _openai_tools(tools)
            kwargs["tool_choice"] = "auto"
        if self.profile.reasoning_effort:
            kwargs["reasoning_effort"] = self.profile.reasoning_effort
        return _openai_response(self._create(kwargs))

    def _create(self, kwargs: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            try:
                return self.client.chat.completions.create(**kwargs)
            except _transient_errors() as exc:
                attempt += 1
                if attempt > _MAX_RETRIES:
                    raise
                backoff = min(_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _RETRY_MAX_DELAY)
                wait = max(backoff + random.uniform(0.0, backoff * 0.25), _retry_after_seconds(exc))
                self.total_retry_wait_s += wait
                time.sleep(wait)


def _provider_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    context: list[str] = []
    converted: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "system_context":
            context.append(content)
        elif role == "tool":
            converted.append({"role": "user", "content": f"Tool result {message.get('tool_name')}: {content}"})
        else:
            converted.append({"role": "user" if role not in {"assistant", "user"} else role, "content": content})
    return "\n\n".join(context), converted


def _openai_tools(tools: list[ToolSchema]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters}}
        for tool in tools
    ]


def _openai_response(response: Any) -> LLMResponse:
    choices = getattr(response, "choices", []) or []
    message = getattr(choices[0], "message", None) if choices else None
    calls = [_openai_call(call) for call in (getattr(message, "tool_calls", None) or [])]
    usage = getattr(response, "usage", None)
    text = _message_text(getattr(message, "content", "") if message else "")
    return LLMResponse(text=text or None, tool_calls=tuple(calls), tokens_in=_usage(usage, "prompt_tokens"), tokens_out=_usage(usage, "completion_tokens"))


def _openai_call(call: Any) -> ToolCall:
    function = getattr(call, "function", None)
    return ToolCall(
        name=str(getattr(function, "name", "") or ""),
        args=_json_args(getattr(function, "arguments", "") or ""),
        id=getattr(call, "id", None),
    )


def _message_text(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict) and item.get("type") == "text").strip()
    return str(content or "").strip()


def _json_args(raw: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw or "{}")
    except Exception:
        return {"_raw_arguments": raw}
    return loaded if isinstance(loaded, dict) else {"_raw_arguments": raw}


def _usage(usage: Any, name: str) -> int:
    return int(getattr(usage, name, 0) or 0)


def _join(system: str, context: str) -> str:
    return f"{system}\n\n{context}".strip() if context else system
