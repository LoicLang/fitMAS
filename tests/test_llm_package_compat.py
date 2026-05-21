from __future__ import annotations


def test_fitmas_llm_is_normal_package_not_decision_legacy_alias() -> None:
    import fitmas.llm as llm

    assert llm.__name__ == "fitmas.llm"
    assert not hasattr(llm, "CoachDecision")
    assert not hasattr(llm, "MutationDecision")
    assert not hasattr(llm, "decide")


def test_legacy_contracts_no_longer_expose_coachdecision_or_parser() -> None:
    import fitmas.legacy.decision_contracts as contracts

    assert not hasattr(contracts, "CoachDecision")
    assert not hasattr(contracts, "PendingResolution")


def test_llm_gateway_root_wrapper_is_deleted() -> None:
    from fitmas.llm.gateway import request_json, request_text

    assert callable(request_json)
    assert callable(request_text)
