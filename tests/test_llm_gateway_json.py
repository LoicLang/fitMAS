from __future__ import annotations

import unittest
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import fitmas.llm_gateway as gw


def _fake_text_response(text: str) -> SimpleNamespace:
    """Mimic the shape Anthropic SDK responses expose to our gateway."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
    )


class LLMGatewayJsonTest(unittest.TestCase):
    """Gateway-level JSON parsing must be as robust as llm._request_json.

    Both request_json() (which re-enters via request_text) and
    message_json() (which reads an already-returned response object)
    feed downstream deterministic parsers; a raw json.loads() there
    silently drops valid-but-slightly-messy LLM outputs."""

    def test_request_json_repairs_truncated_tail(self) -> None:
        original_request_text = gw.request_text
        try:
            gw.request_text = lambda **kwargs: (
                '{"adaptations":[{"action":"replace","session_id":8,"new_duration_min":25,'
                '"rationale":"ok"}],"message":"Je coupe la natation'
            )
            data = gw.request_json(system="x", prompt="y")
        finally:
            gw.request_text = original_request_text

        self.assertIsNotNone(data)
        self.assertEqual(data["adaptations"][0]["session_id"], 8)
        self.assertEqual(data["message"], "Je coupe la natation")

    def test_request_json_extracts_balanced_prefix_before_tail_noise(self) -> None:
        original_request_text = gw.request_text
        try:
            gw.request_text = lambda **kwargs: (
                '{"mutation_type":"no_change","rationale":"ok",'
                '"fitmas_message":"Bien recu."}\nnotes bavardes du modele'
            )
            data = gw.request_json(system="x", prompt="y")
        finally:
            gw.request_text = original_request_text

        self.assertIsNotNone(data)
        self.assertEqual(data["mutation_type"], "no_change")

    def test_message_json_repairs_truncated_tail(self) -> None:
        response = _fake_text_response(
            '{"verdict":"ok","items":[{"id":1,"label":"a"},{"id":2,"label":"b"'
        )
        data = gw.message_json(response)

        self.assertIsNotNone(data)
        self.assertEqual(data["verdict"], "ok")
        self.assertEqual(data["items"][0]["id"], 1)
        self.assertEqual(data["items"][1]["id"], 2)

    def test_message_json_extracts_balanced_prefix_before_tail_noise(self) -> None:
        response = _fake_text_response(
            '{"mutation_type":"no_change","rationale":"ok",'
            '"fitmas_message":"Bien recu."}\nnotes bavardes du modele'
        )
        data = gw.message_json(response)

        self.assertIsNotNone(data)
        self.assertEqual(data["mutation_type"], "no_change")


class LLMGatewayProviderTest(unittest.TestCase):
    def test_client_prefers_deepseek_v4_when_deepseek_key_is_configured(self) -> None:
        created: dict[str, object] = {}

        class FakeAnthropicModule:
            class Anthropic:
                def __init__(self, **kwargs):
                    created.update(kwargs)

        with patch.dict(sys.modules, {"anthropic": FakeAnthropicModule}):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-test"}, clear=True):
                client = gw.client()

        self.assertIsNotNone(client)
        self.assertEqual(created["api_key"], "sk-ds-test")
        self.assertEqual(created["base_url"], "https://api.deepseek.com/anthropic")

    def test_request_message_defaults_to_deepseek_v4_pro(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeMessages:
            def create(self, **kwargs):
                calls.append(kwargs)
                return _fake_text_response("ok")

        fake_client = SimpleNamespace(messages=FakeMessages())

        with patch.object(gw, "client", lambda: fake_client):
            gw.request_message(
                system="system",
                messages=[{"role": "user", "content": "hello"}],
            )

        self.assertEqual(calls[0]["model"], "deepseek-v4-pro")

    def test_request_message_maps_legacy_claude_models_when_using_deepseek(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeMessages:
            def create(self, **kwargs):
                calls.append(kwargs)
                return _fake_text_response("ok")

        fake_client = SimpleNamespace(messages=FakeMessages())

        with patch.object(gw, "client", lambda: fake_client):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-test"}, clear=True):
                gw.request_message(
                    system="system",
                    messages=[{"role": "user", "content": "hello"}],
                    model="claude-haiku-4-5-20251001",
                )
                gw.request_message(
                    system="system",
                    messages=[{"role": "user", "content": "hello"}],
                    model="claude-sonnet-4-6",
                )

        self.assertEqual(calls[0]["model"], "deepseek-v4-flash")
        self.assertEqual(calls[1]["model"], "deepseek-v4-pro")

    def test_request_message_disables_thinking_by_default_for_deepseek(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeMessages:
            def create(self, **kwargs):
                calls.append(kwargs)
                return _fake_text_response("ok")

        fake_client = SimpleNamespace(messages=FakeMessages())

        with patch.object(gw, "client", lambda: fake_client):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-test"}, clear=True):
                gw.request_message(
                    system="system",
                    messages=[{"role": "user", "content": "hello"}],
                )

        self.assertEqual(calls[0]["thinking"], {"type": "disabled"})

    def test_request_structured_json_uses_deepseek_openai_json_object(self) -> None:
        created: dict[str, object] = {}
        calls: list[dict[str, object]] = []

        class FakeOpenAIClient:
            def __init__(self, **kwargs):
                created.update(kwargs)
                self.chat = SimpleNamespace(completions=self)

            def create(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content='{"mutation_type":"no_change","rationale":"ok","fitmas_message":"OK."}')
                        )
                    ]
                )

        fake_openai_module = SimpleNamespace(OpenAI=FakeOpenAIClient)

        with patch.dict(sys.modules, {"openai": fake_openai_module}):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-test"}, clear=True):
                result = gw.request_structured_json(
                    system="system",
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=256,
                )

        self.assertEqual(created["api_key"], "sk-ds-test")
        self.assertEqual(created["base_url"], "https://api.deepseek.com")
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertGreaterEqual(calls[0]["max_tokens"], 2048)
        self.assertIn("JSON", calls[0]["messages"][0]["content"])
        self.assertEqual(result.provider, "deepseek_openai")
        self.assertEqual(result.data["mutation_type"], "no_change")

    def test_request_structured_json_retries_empty_deepseek_content_with_stronger_prompt(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeOpenAIClient:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=self)

            def create(self, **kwargs):
                calls.append(kwargs)
                content = "" if len(calls) == 1 else '{"mutation_type":"no_change","rationale":"retry","fitmas_message":"OK."}'
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        fake_openai_module = SimpleNamespace(OpenAI=FakeOpenAIClient)

        with patch.dict(sys.modules, {"openai": fake_openai_module}):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-test"}, clear=True):
                result = gw.request_structured_json(
                    system="system",
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=128,
                    provider="deepseek_openai",
                )

        self.assertEqual(result.provider, "deepseek_openai")
        self.assertEqual(result.data["rationale"], "retry")
        self.assertEqual(len(calls), 2)
        self.assertIn("Tentative 2", calls[1]["messages"][0]["content"])

    def test_request_structured_json_falls_back_to_claude_when_deepseek_openai_fails(self) -> None:
        anthropic_calls: list[dict[str, object]] = []

        class FailingOpenAIClient:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=self)

            def create(self, **kwargs):
                raise RuntimeError("deepseek openai down")

        class FakeAnthropicMessages:
            def create(self, **kwargs):
                anthropic_calls.append(kwargs)
                return _fake_text_response('{"mutation_type":"no_change","rationale":"fallback","fitmas_message":"OK fallback."}')

        class FakeAnthropicClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.messages = FakeAnthropicMessages()

        fake_openai_module = SimpleNamespace(OpenAI=FailingOpenAIClient)

        class FakeAnthropicModule:
            Anthropic = FakeAnthropicClient

        with patch.dict(sys.modules, {"openai": fake_openai_module, "anthropic": FakeAnthropicModule}):
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-ds-test", "ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
                result = gw.request_structured_json(
                    system="system",
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=256,
                )

        self.assertEqual(result.provider, "claude_anthropic")
        self.assertTrue(result.provider_fallback_used)
        self.assertEqual(result.data["rationale"], "fallback")
        self.assertEqual(anthropic_calls[0]["model"], "claude-haiku-4-5-20251001")


if __name__ == "__main__":
    unittest.main()
