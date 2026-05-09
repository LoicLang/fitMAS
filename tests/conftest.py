from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


BACKEND_SRC = Path(__file__).resolve().parents[1] / "backend" / "src"
PROVIDER_KEY_ENV_VARS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
REAL_LLM_TEST_FLAG = "FITMAS_RUN_REAL_LLM_TESTS"

if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

os.environ.setdefault("FITMAS_ENABLE_FINAL_REPLY_COMPOSER", "0")


def _real_llm_tests_enabled() -> bool:
    return os.getenv(REAL_LLM_TEST_FLAG) == "1"


def _scrub_provider_keys_from_pytest_env() -> None:
    if _real_llm_tests_enabled():
        return
    for key in PROVIDER_KEY_ENV_VARS:
        os.environ.pop(key, None)


_scrub_provider_keys_from_pytest_env()


@pytest.fixture(autouse=True)
def scrub_real_llm_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep normal tests offline even when the developer shell has real keys."""
    if _real_llm_tests_enabled():
        return
    for key in PROVIDER_KEY_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
