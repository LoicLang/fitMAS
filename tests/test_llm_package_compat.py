from __future__ import annotations


def test_fitmas_llm_is_normal_package_not_decision_legacy_alias() -> None:
    import fitmas.llm as llm

    assert llm.__name__ == "fitmas.llm"
    assert hasattr(llm, "CoachDecision")
    assert hasattr(llm, "decide")


def test_fitmas_llm_package_reexports_legacy_decision_contracts() -> None:
    from fitmas.llm import CoachDecision, decide, parse_coach_decision_payload
    from fitmas.llm.decision_legacy import CoachDecision as LegacyCoachDecision

    assert CoachDecision is LegacyCoachDecision
    assert callable(decide)
    assert callable(parse_coach_decision_payload)


def test_llm_gateway_wrapper_reexports_new_gateway_module() -> None:
    from fitmas import llm_gateway
    from fitmas.llm import gateway

    assert llm_gateway.request_json is gateway.request_json
    assert llm_gateway.request_text is gateway.request_text
