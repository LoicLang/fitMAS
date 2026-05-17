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

    assert reply == "C'est cale vendredi."
