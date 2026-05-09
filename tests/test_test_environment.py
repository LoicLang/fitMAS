from __future__ import annotations

import os

import pytest


def test_standard_tests_scrub_real_llm_provider_keys() -> None:
    if os.getenv("FITMAS_RUN_REAL_LLM_TESTS") == "1":
        pytest.skip("real LLM test mode intentionally keeps provider keys")

    assert os.getenv("DEEPSEEK_API_KEY") is None
    assert os.getenv("ANTHROPIC_API_KEY") is None
    assert os.getenv("OPENAI_API_KEY") is None
