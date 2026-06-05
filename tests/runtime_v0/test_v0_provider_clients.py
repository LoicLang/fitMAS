from types import SimpleNamespace

from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolSchema
from scripts.v0_eval.provider_clients import (
    MeteredLLMClient,
    OpenAICompatibleToolClient,
    provider_profile,
)


def test_provider_profile_resolves_defaults_and_env_names():
    profiles = {name: provider_profile(name) for name in ("gemini", "grok", "deepseek", "mistral")}

    assert profiles["deepseek"].api_key_env == "DEEPSEEK_API_KEY"
    assert profiles["gemini"].api_key_env == "GEMINI_API_KEY"
    assert profiles["grok"].api_key_env == "XAI_API_KEY"
    assert profiles["grok"].api_key_env_aliases == ("GROK_API_KEY",)
    assert profiles["mistral"].api_key_env == "MISTRAL_API_KEY"
    assert profiles["deepseek"].base_url == "https://api.deepseek.com"
    assert profiles["mistral"].base_url == "https://api.mistral.ai/v1"
    assert profiles["mistral"].model == "mistral-medium-2604"
    assert all(profile.model for profile in profiles.values())


def test_openai_compatible_client_parses_tool_calls():
    fake_client = _fake_openai_client(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="get_current_plan",
                                    arguments='{"days": 7}',
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
        )
    )
    client = OpenAICompatibleToolClient(provider_profile("deepseek"), client=fake_client)

    response = client.chat_with_tools("system", [{"role": "user", "content": "plan ?"}], [_tool()])

    assert fake_client.chat.completions.last_kwargs["top_p"] == 1
    assert response.text is None
    assert response.tool_calls[0].name == "get_current_plan"
    assert response.tool_calls[0].args == {"days": 7}
    assert response.tokens_in == 12
    assert response.tokens_out == 3


def test_openai_compatible_client_encodes_runtime_tool_results_as_user_messages():
    fake_client = _fake_openai_client(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))]))
    client = OpenAICompatibleToolClient(provider_profile("gemini"), client=fake_client)

    response = client.chat_with_tools(
        "system",
        [
            {"role": "system_context", "content": "today: 2026-05-22"},
            {"role": "tool", "tool_name": "get_current_plan", "content": '{"sessions": []}'},
        ],
        [],
    )

    sent = fake_client.chat.completions.last_kwargs["messages"]
    assert sent[0]["role"] == "system"
    assert sent[1]["content"].startswith("Tool result get_current_plan:")
    assert response.text == "ok"


def test_openai_compatible_client_ignores_reasoning_content_blocks():
    fake_client = _fake_openai_client(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[
                            {"type": "thinking", "thinking": [{"type": "text", "text": "hidden"}]},
                            {"type": "text", "text": "Visible reply."},
                        ],
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
        )
    )
    client = OpenAICompatibleToolClient(provider_profile("mistral"), client=fake_client)

    response = client.chat_with_tools("system", [], [])

    assert response.text == "Visible reply."


def test_metered_client_accumulates_tokens_and_calls():
    class _Client:
        def chat_with_tools(self, *_):
            return LLMResponse(text="ok", tokens_in=5, tokens_out=3)

    client = MeteredLLMClient(_Client(), provider="deepseek", model="deepseek-v4-pro")

    client.chat_with_tools("system", [], [])
    client.chat_with_tools("system", [], [])

    assert client.calls == 2
    assert client.tokens_in == 10
    assert client.tokens_out == 6


def _tool() -> ToolSchema:
    return ToolSchema(
        name="get_current_plan",
        description="Read current plan",
        parameters={"type": "object", "properties": {"days": {"type": "integer"}}},
        handler=lambda **_: {},
        is_proposal=False,
    )


def _fake_openai_client(response):
    class _Completions:
        def create(self, **kwargs):
            self.last_kwargs = kwargs
            return response

    completions = _Completions()
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))
