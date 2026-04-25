#!/usr/bin/env python3
"""Spike DeepSeek through the OpenAI-compatible SDK.

This is intentionally not wired into FitMAS runtime. It answers one question:
does DeepSeek behave better for JSON/tool-use through the OpenAI API surface
than through the Anthropic-compatible surface?
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
load_dotenv(ROOT / ".env")

from fitmas.llm_gateway import _robust_json_loads  # noqa: E402


DEFAULT_MODEL_CANDIDATES = (
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-chat",
)
BASE_URL = "https://api.deepseek.com"


@dataclass(slots=True)
class CaseResult:
    name: str
    ok: bool
    model: str | None = None
    latency_ms: int | None = None
    parsed: dict[str, Any] | None = None
    raw_preview: str | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DeepSeek OpenAI SDK structured-output spike.")
    parser.add_argument(
        "--models",
        default=os.getenv("DEEPSEEK_OPENAI_MODELS", ",".join(DEFAULT_MODEL_CANDIDATES)),
        help="Comma-separated model candidates. First working model is used.",
    )
    args = parser.parse_args()

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY missing.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI
    except ImportError:
        print("openai package missing. Run: .venv/bin/python -m pip install -e .", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    model_candidates = tuple(candidate.strip() for candidate in args.models.split(",") if candidate.strip())
    if not model_candidates:
        print("No model candidates provided.", file=sys.stderr)
        return 2

    selected_model, selection_results = select_working_model(client, model_candidates)
    results: list[CaseResult] = selection_results

    if selected_model is None:
        print(json.dumps({"selected_model": None, "results": [asdict(item) for item in results]}, ensure_ascii=False, indent=2))
        return 1

    results.extend(
        [
            run_json_direct(client, selected_model),
            run_tool_then_json(client, selected_model),
            run_strict_decision_tool(client, selected_model),
        ]
    )

    summary = {
        "provider": "deepseek-openai-compatible",
        "base_url": BASE_URL,
        "selected_model": selected_model,
        "ok": all(item.ok for item in results if not item.name.startswith("model_probe:")),
        "results": [asdict(item) for item in results],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


def select_working_model(client: Any, candidates: tuple[str, ...]) -> tuple[str | None, list[CaseResult]]:
    results: list[CaseResult] = []
    for model in candidates:
        started = perf_counter()
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                max_tokens=64,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": 'Return {"ok":true,"probe":"model"} as JSON.'},
                ],
            )
            raw = _message_content(response)
            parsed = _robust_json_loads(raw or "")
            ok = bool(parsed and parsed.get("ok") is True)
            result = CaseResult(
                name=f"model_probe:{model}",
                ok=ok,
                model=model,
                latency_ms=_elapsed_ms(started),
                parsed=parsed,
                raw_preview=_preview(raw),
            )
            results.append(result)
            if ok:
                return model, results
        except Exception as exc:
            results.append(
                CaseResult(
                    name=f"model_probe:{model}",
                    ok=False,
                    model=model,
                    latency_ms=_elapsed_ms(started),
                    error=_exception_summary(exc),
                )
            )
    return None, results


def run_json_direct(client: Any, model: str) -> CaseResult:
    started = perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=512,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are FitMAS. Return JSON only with keys: "
                        "mutation_type, rationale, fitmas_message."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Contexte: vendredi 24 avril 2026. "
                        "Message utilisateur: Salut, ca va ? "
                        "Return a no_change decision as JSON. Keep values short."
                    ),
                },
            ],
        )
        raw = _message_content(response)
        parsed = _robust_json_loads(raw or "")
        ok = _decision_like(parsed, expected="no_change")
        return CaseResult(
            name="json_direct",
            ok=ok,
            model=model,
            latency_ms=_elapsed_ms(started),
            parsed=parsed,
            raw_preview=_preview(raw),
        )
    except Exception as exc:
        return CaseResult(name="json_direct", ok=False, model=model, latency_ms=_elapsed_ms(started), error=_exception_summary(exc))


def run_tool_then_json(client: Any, model: str) -> CaseResult:
    started = perf_counter()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_today_context",
                "description": "Read today's planned session and recent reality.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are FitMAS. You may call tools. After tool results, "
                "return JSON only with keys mutation_type, rationale, fitmas_message."
            ),
        },
        {
            "role": "user",
            "content": "Je suis rince aujourd'hui, jambes lourdes. Que fait-on ?",
        },
    ]
    try:
        first = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=256,
            tools=tools,
            tool_choice="auto",
            messages=messages,
        )
        first_message = first.choices[0].message
        tool_calls = list(first_message.tool_calls or [])
        if not tool_calls:
            raw = first_message.content or ""
            return CaseResult(
                name="tool_then_json",
                ok=False,
                model=model,
                latency_ms=_elapsed_ms(started),
                raw_preview=_preview(raw),
                error="model_did_not_call_tool",
                extra={"finish_reason": first.choices[0].finish_reason},
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": first_message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": call.type,
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ],
        }
        reasoning_content = getattr(first_message, "reasoning_content", None)
        if reasoning_content:
            # DeepSeek's OpenAI-compatible API requires this field to be replayed
            # when the assistant used thinking before a tool call.
            assistant_message["reasoning_content"] = reasoning_content
        messages.append(assistant_message)
        for call in tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        {
                            "today": "2026-04-24",
                            "planned": {
                                "session_id": 42,
                                "sport_type": "running",
                                "title": "Footing facile",
                                "duration_min": 40,
                            },
                            "recent_reality": "2 sorties offplan cette semaine, fatigue signalee aujourd'hui.",
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        final = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=384,
            response_format={"type": "json_object"},
            messages=messages,
        )
        raw = _message_content(final)
        parsed = _robust_json_loads(raw or "")
        schema_ok = bool(parsed and parsed.get("mutation_type") in {"no_change", "lighten_day", "replace_session"})
        ok = _decision_like(parsed)
        return CaseResult(
            name="tool_then_json",
            ok=ok,
            model=model,
            latency_ms=_elapsed_ms(started),
            parsed=parsed,
            raw_preview=_preview(raw),
            extra={
                "tool_call_count": len(tool_calls),
                "tool_names": [call.function.name for call in tool_calls],
                "fitmas_schema_ok": schema_ok,
            },
        )
    except Exception as exc:
        return CaseResult(name="tool_then_json", ok=False, model=model, latency_ms=_elapsed_ms(started), error=_exception_summary(exc))


def run_strict_decision_tool(client: Any, model: str) -> CaseResult:
    started = perf_counter()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "emit_coach_decision",
                "description": "Emit the final FitMAS coach decision.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mutation_type": {
                            "type": "string",
                            "enum": ["no_change", "move_session", "swap_sessions", "lighten_day", "replace_session"],
                        },
                        "target_session_id": {"type": ["integer", "null"]},
                        "target_date": {"type": ["string", "null"]},
                        "rationale": {"type": "string"},
                        "fitmas_message": {"type": "string"},
                    },
                    "required": [
                        "mutation_type",
                        "target_session_id",
                        "target_date",
                        "rationale",
                        "fitmas_message",
                    ],
                    "additionalProperties": False,
                },
            },
        }
    ]
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=768,
            tools=tools,
            tool_choice="auto",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are FitMAS. You must emit the final decision by calling "
                        "emit_coach_decision. Do not answer in text."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Calendrier: id=42 vendredi footing facile, id=43 samedi tempo. "
                        "Utilisateur: Je ne peux pas ce soir. "
                        "Decide safely."
                    ),
                },
            ],
        )
        message = response.choices[0].message
        tool_calls = list(message.tool_calls or [])
        parsed = None
        if tool_calls:
            parsed = _robust_json_loads(tool_calls[0].function.arguments or "")
        schema_ok = bool(parsed and parsed.get("mutation_type") in {"lighten_day", "move_session", "swap_sessions", "no_change"})
        ok = _decision_like(parsed)
        return CaseResult(
            name="strict_decision_tool",
            ok=ok,
            model=model,
            latency_ms=_elapsed_ms(started),
            parsed=parsed,
            raw_preview=_preview(message.content),
            extra={
                "finish_reason": response.choices[0].finish_reason,
                "tool_call_count": len(tool_calls),
                "tool_name": tool_calls[0].function.name if tool_calls else None,
                "fitmas_schema_ok": schema_ok,
            },
        )
    except Exception as exc:
        return CaseResult(name="strict_decision_tool", ok=False, model=model, latency_ms=_elapsed_ms(started), error=_exception_summary(exc))


def _message_content(response: Any) -> str:
    return str(response.choices[0].message.content or "").strip()


def _decision_like(parsed: dict[str, Any] | None, *, expected: str | None = None) -> bool:
    if not isinstance(parsed, dict):
        return False
    if expected is not None and parsed.get("mutation_type") != expected:
        return False
    return bool(parsed.get("fitmas_message")) and bool(parsed.get("rationale"))


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _preview(raw: str | None, *, limit: int = 260) -> str | None:
    if raw is None:
        return None
    return raw[:limit]


def _exception_summary(exc: Exception) -> str:
    message = str(exc)
    if len(message) > 400:
        message = message[:400] + "..."
    return f"{type(exc).__name__}: {message}"


if __name__ == "__main__":
    raise SystemExit(main())
