from __future__ import annotations

import fitmas.llm.legacy_provider as legacy_provider


def test_legacy_provider_deepseek_structured_default_enabled(monkeypatch) -> None:
    monkeypatch.delenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", raising=False)

    assert legacy_provider.use_deepseek_openai_structured_output() is True


def test_legacy_provider_deepseek_structured_can_disable(monkeypatch) -> None:
    monkeypatch.setenv("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", "false")

    assert legacy_provider.use_deepseek_openai_structured_output() is False


def test_legacy_provider_deepseek_tool_thinking_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("FITMAS_DEEPSEEK_TOOL_THINKING", "1")

    assert legacy_provider.deepseek_tool_thinking_kwargs() == {}


def test_legacy_provider_deepseek_tool_thinking_normalizes_effort(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("FITMAS_DEEPSEEK_TOOL_THINKING", "1")
    monkeypatch.setenv("FITMAS_DEEPSEEK_TOOL_THINKING_EFFORT", "invalid")

    assert legacy_provider.deepseek_tool_thinking_kwargs() == {
        "thinking": {"type": "enabled"},
        "output_config": {"effort": "high"},
    }


def test_legacy_provider_request_json_uses_injected_request_text() -> None:
    data = legacy_provider.request_json(
        system="system",
        prompt="prompt",
        request_text_fn=lambda **_kwargs: '{"response_type":"no_change","rationale":"ok","fitmas_message":"Vu."}',
    )

    assert data == {
        "mutation_type": "no_change",
        "response_type": "no_change",
        "rationale": "ok",
        "fitmas_message": "Vu.",
    }


def test_legacy_provider_structured_json_uses_injected_local_json_path_when_patched(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    sentinel_request_json = lambda **_kwargs: {"response_type": "no_change"}

    data = legacy_provider.request_structured_json(
        system="system",
        messages=[{"role": "user", "content": "prompt"}],
        request_json_fn=sentinel_request_json,
        default_request_json_fn=legacy_provider.request_json,
        request_message_fn=legacy_provider.request_message,
        default_request_message_fn=legacy_provider.request_message,
    )

    assert data == {"response_type": "no_change"}
