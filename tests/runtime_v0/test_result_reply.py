from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.executor import CommandEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.policy import PolicyDecision
from fitmas.runtime_v0.proposals import ActionProposal
from fitmas.runtime_v0.reply import ReplyComposer
from fitmas.runtime_v0.result import build_runtime_result
from fitmas.runtime_v0.snapshot import PendingView, SnapshotBuilder
from fitmas.runtime_v0.db import init_db


PARIS = ZoneInfo("Europe/Paris")


def _event() -> InputEvent:
    return InputEvent(
        id="evt-1",
        user_id=1,
        source="test",
        type="user_message",
        text="Plan actuel ?",
        payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )


def _snapshot(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    return SnapshotBuilder(db_path).build(1, _event().occurred_at)


def _applied_event() -> CommandEvent:
    return CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="SetSessionStatusCommand",
        target_type="session",
        target_id="60",
        status="applied",
        before={"status": "planned"},
        after={"status": "skipped"},
        reason="user skipped",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )


def test_build_runtime_result_carries_commits_blocks_pending_and_contract():
    event = _event()
    proposal = ActionProposal(
        type="execution_update",
        confidence=0.8,
        user_intent_summary="skipped",
        evidence=("user skipped",),
    )
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="move key session",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    policy = PolicyDecision(
        action="create_pending",
        reason="needs confirmation",
        risk_level="medium",
        commands=(),
        reply_facts=("confirmation needed",),
    )

    result = build_runtime_result(
        event=event,
        turn_id="turn-1",
        proposal=proposal,
        policy=policy,
        command_events=(_applied_event(),),
        pending=pending,
        blocked_reasons=("blocked detail",),
    )

    assert result.event_id == "evt-1"
    assert result.proposal_type == "execution_update"
    assert result.policy_action == "create_pending"
    assert result.committed_events[0].target_id == "60"
    assert result.pending is pending
    assert "confirmation needed" in result.reply_contract.must_include
    assert "blocked detail" in result.blocked_reasons
    assert result.reply_contract.tone == "explaining_block"

    pending_only = build_runtime_result(
        event=event,
        turn_id="turn-2",
        proposal=proposal,
        policy=policy,
        command_events=(),
        pending=pending,
    )
    assert pending_only.reply_contract.tone == "asking"


def test_reply_composer_uses_llm_response_and_fallbacks(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    proposal = ActionProposal(
        type="answer",
        confidence=0.8,
        user_intent_summary="answer",
        evidence=("2026-05-22 Footing",),
        answer_facts=("2026-05-22 Footing",),
    )
    policy = PolicyDecision(
        action="answer_only",
        reason="answer",
        risk_level="low",
        commands=(),
        reply_facts=("2026-05-22 Footing",),
    )
    result = build_runtime_result(event, "turn-1", proposal, policy, ())
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Aujourd'hui: Footing.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Aujourd'hui: Footing."

    failing = ReplyComposer(FakeLLMClient([]), "reply-system")
    assert failing.compose(result, snapshot) == "2026-05-22 Footing"

    non_answer = build_runtime_result(
        event,
        "turn-2",
        ActionProposal(type="no_send", confidence=0.0, user_intent_summary="none", evidence=()),
        PolicyDecision(action="no_send", reason="none", risk_level="low", commands=(), reply_facts=()),
        (),
    )
    assert failing.compose(non_answer, snapshot) == "Je n'ai pas pu traiter ça proprement. Réessaie dans un instant."


def test_reply_composer_retries_plan_answer_that_omits_read_sessions(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    read_fact = (
        '{"sessions": ['
        '{"date": "2026-05-22", "title": "Footing recup"},'
        '{"date": "2026-05-24", "title": "VMA courte"},'
        '{"date": "2026-05-26", "title": "Endurance"}'
        ']}'
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="answer", confidence=0.8, user_intent_summary="answer", evidence=(read_fact,), answer_facts=(read_fact,)),
        PolicyDecision(action="answer_only", reason="answer", risk_level="low", commands=(), reply_facts=(read_fact,)),
        (),
    )
    client = FakeLLMClient(
        [
            LLMResponse(text="Aujourd'hui footing."),
            LLMResponse(text="22 Footing recup. 24 VMA courte. 26 Endurance."),
        ]
    )
    composer = ReplyComposer(client, "reply-system")

    reply = composer.compose(result, snapshot)

    assert reply == "22 Footing recup. 24 VMA courte. 26 Endurance."
    assert "Réponse rejetée" in client.requests[1]["system"]


def test_reply_composer_returns_clarification_question_without_llm(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="ask_clarification", confidence=1.0, user_intent_summary="clarify", evidence=()),
        PolicyDecision(
            action="ask_clarification",
            reason="clarify",
            risk_level="low",
            commands=(),
            reply_facts=("Quelle séance ?",),
        ),
        (),
    )

    assert ReplyComposer(FakeLLMClient([]), "reply-system").compose(result, snapshot) == "Quelle séance ?"


def test_reply_composer_pending_fallback_asks_confirmation(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="déplacer la VMA à vendredi",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="create_pending", reason="needs confirmation", risk_level="medium", commands=(), reply_facts=()),
        (),
        pending=pending,
    )

    reply = ReplyComposer(FakeLLMClient([]), "reply-system").compose(result, snapshot)

    assert reply == "Je dois confirmer avant de faire ça: déplacer la VMA à vendredi."


def test_reply_composer_fallback_prefers_pending_over_bookkeeping_commit(tmp_path):
    # Bug réel observé sur DeepSeek: sur un tour pending, quand le reply LLM
    # échoue, le filet ne doit pas tomber sur le message technique sec à cause
    # de la commande de bookkeeping (CreatePendingConfirmationCommand) committée.
    # Il doit rendre la demande de confirmation, pas une erreur froide.
    snapshot = _snapshot(tmp_path)
    event = _event()
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="décaler la VMA à vendredi",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    bookkeeping = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="CreatePendingConfirmationCommand",
        target_type="pending",
        target_id="plan_patch",
        status="applied",
        before={},
        after={"id": 2, "type": "plan_patch", "summary": "décaler la VMA à vendredi", "expires_at": "2026-05-23T14:00:00+02:00"},
        reason="needs confirmation",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="create_pending", reason="needs confirmation", risk_level="medium", commands=(), reply_facts=()),
        (bookkeeping,),
        pending=pending,
    )
    composer = ReplyComposer(FakeLLMClient([]), "reply-system")

    assert composer.compose(result, snapshot) == "Je dois confirmer avant de faire ça: décaler la VMA à vendredi."


def test_reply_composer_pending_goes_through_llm_voice(tmp_path):
    # pending n'est plus un cas template: la voix vit dans le LLM, le guard
    # (test_guard) garantit qu'elle ne prétend pas que c'est déjà fait.
    snapshot = _snapshot(tmp_path)
    event = _event()
    pending = PendingView(
        id=2,
        type="plan_patch",
        summary="déplacer la VMA à vendredi",
        expires_at=datetime(2026, 5, 23, 14, 0, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="create_pending", reason="needs confirmation", risk_level="medium", commands=(), reply_facts=()),
        (),
        pending=pending,
    )
    warm = "Tu veux que je décale ta VMA à vendredi ? Dis-moi et je le cale."
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text=warm)]), "reply-system")

    assert composer.compose(result, snapshot) == warm


def test_reply_composer_keeps_voice_on_skipped_without_fact_token(tmp_path):
    # skipped sans durée ne porte aucun fait robuste à exiger (pas de nombre, pas
    # de jour cible, pas de sport). On fait donc confiance à la voix du LLM: le
    # guard reste seul juge qu'elle ne ment pas sur le commit.
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = _applied_event()
    command = CommandEvent(
        id=command.id,
        turn_id=command.turn_id,
        command_type=command.command_type,
        target_type=command.target_type,
        target_id=command.target_id,
        status=command.status,
        before=command.before,
        after={"date": "2026-05-21", "status": "skipped"},
        reason=command.reason,
        created_at=command.created_at,
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="execution_update", confidence=0.8, user_intent_summary="skipped", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    warm = "J’enregistre que tu n’as pas fait la séance d’hier, c’est noté."
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text=warm)]), "reply-system")

    assert composer.compose(result, snapshot) == warm


def test_reply_composer_keeps_voice_when_partial_states_duration(tmp_path):
    # partiel 20 min: le fait robuste est le nombre 20. Si la voix le porte, on
    # la garde telle quelle, sans la remplacer par un template sec.
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="SetSessionStatusCommand",
        target_type="session",
        target_id="73",
        status="applied",
        before={"status": "planned"},
        after={"date": "2026-05-21", "status": "partial", "duration_min": 20},
        reason="partial",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="execution_update", confidence=0.8, user_intent_summary="partial", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    warm = "C’est noté: hier tu as fait 20 minutes, donc partiel."
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text=warm)]), "reply-system")

    assert composer.compose(result, snapshot) == warm


def test_reply_composer_reprompts_then_keeps_voice_when_duration_appears(tmp_path):
    # 1er jet omet le fait (20 min) -> re-prompt une fois -> 2e jet le porte:
    # on garde la voix, on ne tombe pas sur le template.
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="SetSessionStatusCommand",
        target_type="session",
        target_id="73",
        status="applied",
        before={"status": "planned"},
        after={"date": "2026-05-21", "status": "partial", "duration_min": 20},
        reason="partial",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="execution_update", confidence=0.8, user_intent_summary="partial", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    client = FakeLLMClient(
        [
            LLMResponse(text="C’est noté pour hier, séance partielle."),
            LLMResponse(text="Noté: hier, 20 minutes, donc partiel."),
        ]
    )
    composer = ReplyComposer(client, "reply-system")

    reply = composer.compose(result, snapshot)

    assert reply == "Noté: hier, 20 minutes, donc partiel."
    assert "Réponse rejetée" in client.requests[1]["system"]


def test_reply_composer_falls_back_to_template_when_fact_never_stated(tmp_path):
    # la voix omet le fait (20 min) aux deux jets -> filet déterministe.
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="SetSessionStatusCommand",
        target_type="session",
        target_id="73",
        status="applied",
        before={"status": "planned"},
        after={"date": "2026-05-21", "status": "partial", "duration_min": 20},
        reason="partial",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="execution_update", confidence=0.8, user_intent_summary="partial", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    client = FakeLLMClient(
        [
            LLMResponse(text="C’est noté pour hier, séance partielle."),
            LLMResponse(text="Bien reçu, c’est enregistré pour hier."),
        ]
    )
    composer = ReplyComposer(client, "reply-system")

    assert composer.compose(result, snapshot) == "Noté pour hier: partiel, 20 minutes."


def test_reply_composer_uses_committed_plan_patch_summary(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="ApplyPlanPatchCommand",
        target_type="session",
        target_id="60",
        status="applied",
        before={},
        after={"60": {"date": "2026-05-29"}},
        reason="move",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="move", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Déplacement au 29 mai.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Déplacé à vendredi."


def test_reply_composer_localizes_committed_lighten_summary(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="ApplyPlanPatchCommand",
        target_type="session",
        target_id="70",
        status="applied",
        before={"70": {"date": "2026-05-23", "duration_min": 50, "intensity_label": "moderate"}},
        after={"70": {"date": "2026-05-23", "duration_min": 50, "intensity_label": "easy"}},
        reason="lighten",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="lighten", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Modification appliquée.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Allégé demain: 50 minutes, facile."


def test_reply_composer_localizes_committed_replace_summary(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    command = CommandEvent(
        id=1,
        turn_id="turn-1",
        command_type="ApplyPlanPatchCommand",
        target_type="session",
        target_id="71",
        status="applied",
        before={"71": {"date": "2026-05-23", "sport": "run", "intensity_label": "easy"}},
        after={"71": {"date": "2026-05-23", "sport": "bike", "intensity_label": "easy"}},
        reason="replace",
        created_at=datetime(2026, 5, 22, 14, 1, tzinfo=PARIS),
    )
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="replace", evidence=("x",)),
        PolicyDecision(action="allow_commit", reason="x", risk_level="low", commands=(), reply_facts=("x",)),
        (command,),
    )
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text="Modification appliquée.")]), "reply-system")

    assert composer.compose(result, snapshot) == "Remplacé demain par vélo facile."


def test_reply_composer_blocked_goes_through_llm_voice(tmp_path):
    # un blocage n'est plus servi par template: le LLM explique posément, le
    # guard reste seul juge de la vérité. Le filet déterministe ne sert qu'en
    # cas d'échec LLM (test suivant).
    snapshot = _snapshot(tmp_path)
    event = _event()
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="hard", evidence=("hard",)),
        PolicyDecision(action="block", reason="health_fact_blocks_hard", risk_level="high", commands=(), reply_facts=("hard",)),
        (),
    )
    warm = "Là je préfère ne pas charger cette séance dure : ton signal de fatigue est encore actif. On la garde en réserve ?"
    composer = ReplyComposer(FakeLLMClient([LLMResponse(text=warm)]), "reply-system")

    assert composer.compose(result, snapshot) == warm


def test_reply_composer_blocked_fallback_explains_when_llm_fails(tmp_path):
    snapshot = _snapshot(tmp_path)
    event = _event()
    result = build_runtime_result(
        event,
        "turn-1",
        ActionProposal(type="plan_patch", confidence=0.8, user_intent_summary="hard", evidence=("hard",)),
        PolicyDecision(action="block", reason="health_fact_blocks_hard", risk_level="high", commands=(), reply_facts=("hard",)),
        (),
    )
    composer = ReplyComposer(FakeLLMClient([]), "reply-system")

    assert composer.compose(result, snapshot) == "Je bloque: trop risqué avec le signal santé actif."
