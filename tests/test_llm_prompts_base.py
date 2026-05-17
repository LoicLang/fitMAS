from __future__ import annotations

from fitmas.llm.prompts.base import PromptRender, join_sections, render_json_block


def test_join_sections_drops_empty_sections() -> None:
    assert join_sections("A", "", None, "B") == "A\n\nB"


def test_render_json_block_is_stable_and_french_safe() -> None:
    rendered = render_json_block({"reason": "douleur épaule", "duration": 35})

    assert '"reason": "douleur épaule"' in rendered
    assert '"duration": 35' in rendered


def test_prompt_render_exposes_system_and_prompt() -> None:
    render = PromptRender(system="system", prompt="prompt", max_tokens=300)

    assert render.system == "system"
    assert render.prompt == "prompt"
    assert render.max_tokens == 300
