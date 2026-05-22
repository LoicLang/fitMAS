from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILES = tuple((REPO_ROOT / "backend/src/fitmas/llm/prompts").glob("*.py"))
FORBIDDEN_TEST_LEAKS = (
    "Cette semaine je voyage de mercredi a vendredi",
    "Je voyage de mercredi a vendredi",
    "trip_constraint",
    "move_easy_then_confirm",
    "replace_swim_with_bike",
    "swim_unavailable_two_weeks",
    "add_hard_dense",
)


def test_prompts_do_not_embed_smoke_scenarios_as_examples() -> None:
    offenders: list[str] = []
    for path in PROMPT_FILES:
        source = path.read_text()
        for phrase in FORBIDDEN_TEST_LEAKS:
            if phrase in source:
                offenders.append(f"{path.relative_to(REPO_ROOT)} contains {phrase!r}")

    assert offenders == []
