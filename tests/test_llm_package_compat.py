from __future__ import annotations


def test_fitmas_llm_is_normal_package_not_decision_legacy_alias() -> None:
    import fitmas.llm as llm

    assert llm.__name__ == "fitmas.llm"
    assert not hasattr(llm, "CoachDecision")
    assert not hasattr(llm, "MutationDecision")
    assert not hasattr(llm, "decide")


def test_legacy_contracts_live_in_explicit_legacy_module() -> None:
    from fitmas.legacy.decision_contracts import CoachDecision
    from fitmas.llm.decision_legacy import parse_coach_decision_payload

    assert CoachDecision.__name__ == "CoachDecision"
    assert callable(parse_coach_decision_payload)


def test_llm_gateway_wrapper_reexports_new_gateway_module() -> None:
    from fitmas import llm_gateway
    from fitmas.llm import gateway

    assert llm_gateway.request_json is gateway.request_json
    assert llm_gateway.request_text is gateway.request_text
