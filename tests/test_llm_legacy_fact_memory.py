from __future__ import annotations

import fitmas.llm.legacy_fact_memory as legacy_fact_memory


def test_extract_facts_returns_empty_for_invalid_payload() -> None:
    result = legacy_fact_memory.extract_facts(
        "je suis fatigue",
        "Je note.",
        [],
        request_json_fn=lambda **kwargs: {"facts": "not-a-list"},
    )

    assert result == []


def test_extract_facts_normalizes_payloads_and_archive_active_false() -> None:
    def request_json_fn(**kwargs):
        return {
            "facts": [
                {
                    "category": "availability",
                    "key": "",
                    "value": "Piscine fermee deux semaines",
                    "confidence": 0.8,
                    "confirmed": True,
                    "source": "conversation",
                    "action": "archive",
                }
            ]
        }

    facts = legacy_fact_memory.extract_facts(
        "la piscine est fermee",
        "Je garde ca en tete.",
        [],
        request_json_fn=request_json_fn,
    )

    assert len(facts) == 1
    assert facts[0]["category"] == "availability"
    assert facts[0]["key"] == "piscine_fermee_deux_semaines"
    assert facts[0]["active"] is False
    assert facts[0]["ttl"] == "medium"
    assert "planning" in facts[0]["affects"]


def test_extract_facts_filters_non_dict_facts() -> None:
    facts = legacy_fact_memory.extract_facts(
        "prefere le matin",
        "Note.",
        [],
        request_json_fn=lambda **kwargs: {"facts": ["bad", {"category": "preference", "value": "Matin"}]},
    )

    assert len(facts) == 1
    assert facts[0]["category"] == "preference"


def test_select_prompt_facts_returns_bounded_conversation_facts() -> None:
    facts = [
        {
            "category": "preference",
            "key": f"pref_{index}",
            "value": f"Preference {index}",
            "confidence": 0.7,
            "confirmed": True,
            "active": True,
            "affects": ["conversation"],
        }
        for index in range(8)
    ]

    selected = legacy_fact_memory.select_prompt_facts(facts)

    assert len(selected) == 6
    assert all(item.startswith("[preference]") for item in selected)


def test_slug_fallback_is_stable_for_missing_key() -> None:
    fact = legacy_fact_memory.extract_facts(
        "objectif trail",
        "Note.",
        [],
        request_json_fn=lambda **kwargs: {"facts": [{"category": "goal", "value": ""}]},
    )[0]

    assert fact["key"] == "fact"
