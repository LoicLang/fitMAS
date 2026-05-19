from __future__ import annotations

from fitmas.decision import DecisionExplanation, ReplyContract
from fitmas.decision.reply_request import ReplyRequest
from fitmas.legacy.final_reply_backend import LegacyFinalReplyBackend


def _request(kind: str) -> ReplyRequest:
    return ReplyRequest(
        kind=kind,  # type: ignore[arg-type]
        user_text="deplace la seance",
        committed_events=("Footing deplace vendredi.",) if kind == "plan_committed" else (),
        blocked_reasons=("Aucune option valide.",) if kind == "plan_blocked" else (),
        pending_summary="Option possible, confirmation recommandee." if kind == "plan_pending" else None,
        memory_updates=(),
        execution_updates=(),
        candidate_summaries=("move_friday: deplacer vendredi",),
        explanation=DecisionExplanation(
            decision_label="label",
            reason_summary="reason",
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        contract=ReplyContract(mode=kind, audience="telegram", allowed_claims=(), forbidden_claims=()),
    )


def test_backend_uses_plan_adaptation_reply_for_pending() -> None:
    calls = []

    def fake_request_text(**kwargs):
        calls.append(kwargs["prompt"])
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"pending ok","repaired_reply":""}'
        return "Je te propose vendredi. Tu confirmes ?"

    reply = LegacyFinalReplyBackend(request_text_fn=fake_request_text, verifier_text_fn=fake_request_text).compose(
        _request("plan_pending")
    )

    assert reply == "Je te propose vendredi. Tu confirmes ?"
    assert any("Confirmation en attente" in prompt for prompt in calls)


def test_backend_uses_committed_events_for_commit() -> None:
    def fake_request_text(**kwargs):
        if "Reponse sortante a verifier:" in kwargs["prompt"]:
            return '{"verdict":"allow","reason":"event ok","repaired_reply":""}'
        return "C'est cale vendredi."

    reply = LegacyFinalReplyBackend(request_text_fn=fake_request_text, verifier_text_fn=fake_request_text).compose(
        _request("plan_committed")
    )

    assert reply == "Footing deplace vendredi."


def test_backend_humanizes_machine_replace_summary_for_user() -> None:
    request = _request("plan_pending")
    request = ReplyRequest(
        kind=request.kind,
        user_text=request.user_text,
        committed_events=request.committed_events,
        blocked_reasons=request.blocked_reasons,
        pending_summary=request.pending_summary,
        memory_updates=request.memory_updates,
        execution_updates=request.execution_updates,
        candidate_summaries=(
            "replace_session | target_session_id=4 | new_sport_type=cycling | "
            "new_duration_min=30 | new_intensity=easy",
        ),
        explanation=request.explanation,
        contract=request.contract,
    )

    reply = LegacyFinalReplyBackend(request_text_fn=lambda **_kwargs: "draft").compose(request)

    assert reply == "Je te propose: remplacer la seance ciblee par velo facile, 30 min. Tu confirmes ?"
