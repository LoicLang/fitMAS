#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"

Expectation = Literal["guarded_no_commit", "no_plan_write", "coherent_commit_or_pending"]


@dataclass(frozen=True)
class SmokeScenario:
    name: str
    prompt: str
    expectation: Expectation
    description: str = ""
    followups: tuple[str, ...] = ()


@dataclass(frozen=True)
class DbSnapshot:
    events: tuple[dict[str, Any], ...]
    pending: tuple[dict[str, Any], ...]
    sessions: tuple[dict[str, Any], ...]
    latest_turn: dict[str, Any] | None
    turns: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ScenarioCheckResult:
    ok: bool
    reasons: list[str]
    warnings: list[str]


SCENARIOS: tuple[SmokeScenario, ...] = (
    SmokeScenario(
        name="move_hard_close",
        prompt="Deplace la seance id 2 'Sortie longue cle' de jeudi a mercredi.",
        expectation="guarded_no_commit",
        description="Regression A+: a risky hard/key move must not bypass WeekCoherence.",
    ),
    SmokeScenario(
        name="replace_key_running_swim_easy",
        prompt="Remplace la seance id 1 'Fractionne seuil' par une natation easy.",
        expectation="guarded_no_commit",
        description="Regression A+: key running stimulus replaced by easy swimming must stay pending/block.",
    ),
    SmokeScenario(
        name="add_hard_dense",
        prompt="Ajoute une seance dure mercredi, meme si la semaine est deja chargee.",
        expectation="guarded_no_commit",
        description="Dense hard-session creation should not commit silently.",
    ),
    SmokeScenario(
        name="occupied_target",
        prompt="Deplace la seance id 2 'Sortie longue cle' de jeudi a samedi.",
        expectation="guarded_no_commit",
        description="Occupied target day should be blocked or pending, never committed.",
    ),
    SmokeScenario(
        name="memory_preference",
        prompt="A partir de maintenant, je prefere courir le matin quand c'est possible.",
        expectation="no_plan_write",
        description="Memory/preference turn must not create planning writes.",
    ),
    SmokeScenario(
        name="move_easy_to_free",
        prompt="Deplace la seance recuperation id 3 a lundi prochain.",
        expectation="coherent_commit_or_pending",
        description="Low-risk planning turn may commit or ask confirmation, but must stay artifact-coherent.",
    ),
    SmokeScenario(
        name="swap_key_and_recovery",
        prompt="Echange le fractionne seuil id 1 avec la recuperation mobilite id 3.",
        expectation="guarded_no_commit",
        description="Swapping a key hard session into a dense window should be guarded.",
    ),
    SmokeScenario(
        name="replace_key_running_strength",
        prompt="Remplace le fractionne seuil id 1 par une seance renfo mobilite facile.",
        expectation="guarded_no_commit",
        description="Replacing the key running stimulus with easy strength should not commit silently.",
    ),
    SmokeScenario(
        name="lighten_key_after_fatigue",
        prompt="Je suis fatigue, allege le fractionne seuil id 1 sans casser la semaine.",
        expectation="coherent_commit_or_pending",
        description="Lightening a key hard day may commit or ask confirmation, but must stay artifact-coherent.",
    ),
    SmokeScenario(
        name="create_easy_free_day",
        prompt="Ajoute un footing facile de 30 minutes lundi prochain.",
        expectation="coherent_commit_or_pending",
        description="Creating an easy support session may commit or ask confirmation, never claim without artifacts.",
    ),
    SmokeScenario(
        name="lookup_current_plan",
        prompt="Redonne-moi le plan actuel, jour par jour.",
        expectation="no_plan_write",
        description="A lookup turn must not write planning artifacts.",
    ),
    SmokeScenario(
        name="ambiguous_move",
        prompt="Mets la course plus tard dans la semaine.",
        expectation="no_plan_write",
        description="An ambiguous planning request should clarify/read, not write a vague mutation.",
    ),
    SmokeScenario(
        name="health_note_no_plan_write",
        prompt="J'ai une petite douleur au genou gauche aujourd'hui, retiens-le pour les prochains ajustements.",
        expectation="no_plan_write",
        description="Health memory should not become a direct planning write by itself.",
    ),
    SmokeScenario(
        name="swim_unavailable_two_weeks",
        prompt="Je ne peux pas nager pendant deux semaines, adapte si besoin sans faire n'importe quoi.",
        expectation="coherent_commit_or_pending",
        description="A multi-day sport constraint may propose a guarded PlanPatch or ask follow-up.",
    ),
    SmokeScenario(
        name="swim_unavailable_no_session",
        prompt="Je ne peux pas nager du 2026-05-13 au 2026-05-14, adapte si besoin.",
        expectation="no_plan_write",
        description="A sport constraint with no matching session in the window should write memory but not create a candidate.",
    ),
)

DAILY_SCENARIOS: tuple[SmokeScenario, ...] = (
    SmokeScenario(
        name="close_turn_ack",
        prompt="Okay chef",
        expectation="no_plan_write",
        description="Social close should stay short, terminal and no-write.",
    ),
    SmokeScenario(
        name="thanks_close",
        prompt="Nickel merci",
        expectation="no_plan_write",
        description="Thanks/ack should not reopen a planning thread.",
    ),
    SmokeScenario(
        name="casual_banter",
        prompt="T'es dur avec moi coach mais ca me va",
        expectation="no_plan_write",
        description="Banter should answer naturally without plan mutation.",
    ),
    SmokeScenario(
        name="body_metric_reassurance_thread",
        prompt="Putain enft je fais 100kg qu'est ce qu'on fait ?",
        expectation="no_plan_write",
        description="Body metric concern should use coach lens without turning into a planning menu.",
        followups=(
            "Rien de grave quoi",
            "Je voulais dire c'est pas grave, si je m'y remets ca va redescendre proprement",
        ),
    ),
    SmokeScenario(
        name="tomorrow_lookup",
        prompt="J'ai quoi demain ?",
        expectation="no_plan_write",
        description="Simple next-day plan lookup should be factual and read-only.",
    ),
    SmokeScenario(
        name="current_plan_lookup",
        prompt="Redonne le plan actuel",
        expectation="no_plan_write",
        description="Current plan lookup should not create events or pending confirmations.",
    ),
    SmokeScenario(
        name="key_session_lookup",
        prompt="C'est quoi la seance la plus importante de la semaine ?",
        expectation="no_plan_write",
        description="Planning explanation should stay read-only.",
    ),
    SmokeScenario(
        name="activity_highlight_lookup",
        prompt="C'etait quoi ma plus longue sortie recente ?",
        expectation="no_plan_write",
        description="Activity history question should use activity highlights, not plan lookup.",
    ),
    SmokeScenario(
        name="load_review_lookup",
        prompt="J'en suis ou niveau charge cette semaine ?",
        expectation="no_plan_write",
        description="Load/readiness question should read context without writing planning artifacts.",
    ),
    SmokeScenario(
        name="execution_done_today",
        prompt="J'ai fait le footing aujourd'hui, 38 minutes tranquille",
        expectation="no_plan_write",
        description="Execution report may update execution state but must not write plan mutation events.",
    ),
    SmokeScenario(
        name="execution_temporal_correction_thread",
        prompt="J'ai couru aujourd'hui 30 minutes",
        expectation="no_plan_write",
        description="Temporal correction should not create planning writes or false mutation claims.",
        followups=("Non c'etait hier en fait",),
    ),
    SmokeScenario(
        name="missed_session_report",
        prompt="J'ai pas pu faire la seance hier, boulot trop tard",
        expectation="no_plan_write",
        description="Missed-session report should be execution/memory, not a planning mutation.",
    ),
    SmokeScenario(
        name="human_missed_yesterday_short",
        prompt="J'ai pas fait hier",
        expectation="no_plan_write",
        description="Short missed-yesterday report should not invent an execution or planning mutation.",
    ),
    SmokeScenario(
        name="human_done_finally",
        prompt="J'ai fait la seance finalement",
        expectation="no_plan_write",
        description="Elliptical completion report should stay execution-only and avoid planning writes.",
    ),
    SmokeScenario(
        name="ambiguous_this_to_friday",
        prompt="Decale ca a vendredi",
        expectation="no_plan_write",
        description="Ambiguous target 'ca' without active pending should clarify/read, not mutate a plan.",
    ),
    SmokeScenario(
        name="swim_unavailable_two_weeks_human",
        prompt="Je peux pas nager deux semaines",
        expectation="coherent_commit_or_pending",
        description="Human phrasing of a two-week swim constraint should route through canonical planning.",
    ),
    SmokeScenario(
        name="fatigue_keep_light",
        prompt="Je suis rince, mais garde un truc leger",
        expectation="coherent_commit_or_pending",
        description="Fatigue plus light-work request should produce a guarded light candidate or pending.",
    ),
    SmokeScenario(
        name="pending_ok_accept",
        prompt="Deplace la recuperation mobilite id 3 a lundi prochain",
        expectation="coherent_commit_or_pending",
        description="A bare 'ok' with an active pending candidate should resolve through pending_resolution.",
        followups=("ok",),
    ),
    SmokeScenario(
        name="ok_without_pending",
        prompt="ok",
        expectation="no_plan_write",
        description="Bare ok without pending should close or acknowledge without creating artifacts.",
    ),
    SmokeScenario(
        name="pending_modify_saturday",
        prompt="Deplace la recuperation mobilite id 3 a lundi prochain",
        expectation="coherent_commit_or_pending",
        description="'Non plutot samedi' with pending context should modify/reject structurally, not parse locally.",
        followups=("non plutot samedi",),
    ),
    SmokeScenario(
        name="add_hard_tomorrow_loaded",
        prompt="Ajoute une seance dure demain",
        expectation="guarded_no_commit",
        description="Human hard-session request in an already loaded week must not commit silently.",
    ),
    SmokeScenario(
        name="future_evening_unavailable",
        prompt="Demain soir c'est impossible pour moi",
        expectation="coherent_commit_or_pending",
        description="Availability constraint can propose/pending an adaptation, never claim without artifact.",
    ),
    SmokeScenario(
        name="trip_constraint",
        prompt="Je voyage de mercredi a vendredi, adapte si besoin",
        expectation="coherent_commit_or_pending",
        description="Multi-day availability constraint should use candidates/policy.",
    ),
    SmokeScenario(
        name="trip_memory_only",
        prompt="Je voyage de mercredi a vendredi",
        expectation="no_plan_write",
        description="Pure travel availability should persist memory without planning mutation.",
    ),
    SmokeScenario(
        name="new_availability",
        prompt="Finalement je peux vendredi matin",
        expectation="coherent_commit_or_pending",
        description="New availability may become a candidate, but must remain artifact-coherent.",
    ),
    SmokeScenario(
        name="fatigue_tomorrow",
        prompt="Je suis rincé pour demain, jambes lourdes",
        expectation="coherent_commit_or_pending",
        description="Fatigue signal can trigger a lighter candidate or pending confirmation.",
    ),
    SmokeScenario(
        name="shin_pain_signal",
        prompt="J'ai une douleur au tibia ce matin, pas enorme mais je la sens",
        expectation="coherent_commit_or_pending",
        description="Health signal should be remembered and adaptation must be guarded.",
    ),
    SmokeScenario(
        name="knee_pain_but_ack",
        prompt="Ok mais genou douloureux quand meme",
        expectation="coherent_commit_or_pending",
        description="Ack plus health signal should not be swallowed as a trivial close.",
    ),
    SmokeScenario(
        name="avoid_back_to_back",
        prompt="Je veux eviter deux jours d'affilee cette semaine",
        expectation="coherent_commit_or_pending",
        description="Preference/constraint about spacing should not be a hardcoded rest block.",
    ),
    SmokeScenario(
        name="swap_by_day",
        prompt="Echange mercredi et jeudi si c'est mieux sportivement",
        expectation="coherent_commit_or_pending",
        description="Day-based swap should rely on typed refs/candidates and stay coherent.",
    ),
    SmokeScenario(
        name="lighten_tomorrow",
        prompt="Allege demain sans toucher au reste",
        expectation="coherent_commit_or_pending",
        description="Lightening a target day should go through candidate simulation/policy.",
    ),
    SmokeScenario(
        name="replace_swim_with_bike",
        prompt="Remplace la natation dimanche par un velo facile",
        expectation="coherent_commit_or_pending",
        description="Replacement by day/sport should use backend candidate refs when possible.",
    ),
    SmokeScenario(
        name="move_easy_then_confirm",
        prompt="Deplace la recuperation mobilite id 3 a lundi prochain",
        expectation="coherent_commit_or_pending",
        description="Pending/commit path should remain coherent through confirmation.",
        followups=("oui je confirme si tu penses que c'est propre",),
    ),
    SmokeScenario(
        name="confirm_without_pending",
        prompt="oui je confirme",
        expectation="no_plan_write",
        description="Bare confirmation without pending should not create a mutation.",
    ),
    SmokeScenario(
        name="short_slot_preference",
        prompt="samedi",
        expectation="no_plan_write",
        description="Short elliptical answer without an active planning question should not invent a mutation.",
    ),
    SmokeScenario(
        name="ignore_previous",
        prompt="Ignore mon dernier message, on garde comme prevu",
        expectation="no_plan_write",
        description="Cancellation-style turn without pending should close cleanly.",
    ),
)


EXTENDED_SCENARIOS: tuple[SmokeScenario, ...] = (
    SmokeScenario(
        name="pending_reject_move",
        prompt="Deplace la recuperation mobilite id 3 a lundi prochain",
        expectation="coherent_commit_or_pending",
        description="extended pending probe: rejected confirmation should not commit a plan mutation.",
        followups=("non finalement on laisse comme prevu",),
    ),
    SmokeScenario(
        name="pending_confirm_with_change",
        prompt="Deplace la recuperation mobilite id 3 a lundi prochain",
        expectation="coherent_commit_or_pending",
        description="extended pending probe: modified confirmation should not bypass pending safety.",
        followups=("oui mais plutot mardi si c'est possible",),
    ),
    SmokeScenario(
        name="short_no_without_pending",
        prompt="non",
        expectation="no_plan_write",
        description="extended pending probe: short negative answer without pending should be no-write.",
    ),
    SmokeScenario(
        name="execution_yesterday_easy",
        prompt="Hier j'ai fait 42 minutes tranquille en course",
        expectation="no_plan_write",
        description="extended execution probe: yesterday activity report should not write planning events.",
    ),
    SmokeScenario(
        name="execution_wrong_sport_correction",
        prompt="J'ai fait 50 minutes de velo ce matin",
        expectation="no_plan_write",
        description="extended execution probe: sport correction thread should stay execution-only.",
        followups=("en fait c'etait de la course, pas du velo",),
    ),
    SmokeScenario(
        name="execution_longer_than_planned",
        prompt="La sortie longue a dure 1h45, plus long que prevu mais facile",
        expectation="no_plan_write",
        description="extended execution probe: longer-than-planned report should not mutate the plan.",
    ),
    SmokeScenario(
        name="health_adapt_knee",
        prompt="Mon genou tire, adapte la seance de demain si besoin",
        expectation="coherent_commit_or_pending",
        description="extended health probe: pain plus adaptation request should be guarded.",
    ),
    SmokeScenario(
        name="fatigue_memory_only",
        prompt="Je suis fatigue aujourd'hui, note-le juste",
        expectation="no_plan_write",
        description="extended health probe: fatigue memory-only should not create planning pending.",
    ),
    SmokeScenario(
        name="illness_rest_request",
        prompt="Je suis malade, mets-moi au repos pour demain si tu penses que c'est mieux",
        expectation="coherent_commit_or_pending",
        description="extended health probe: illness rest request should stay coherent and guarded.",
    ),
    SmokeScenario(
        name="one_day_unavailable_affected",
        prompt="Je ne suis pas dispo mercredi, adapte la seance si besoin",
        expectation="coherent_commit_or_pending",
        description="extended availability probe: affected day should route through canonical planning.",
    ),
    SmokeScenario(
        name="weekend_unavailable",
        prompt="Je ne peux pas m'entrainer ce week-end, adapte si besoin",
        expectation="coherent_commit_or_pending",
        description="extended availability probe: weekend window should be pending or blocked, not legacy.",
    ),
    SmokeScenario(
        name="availability_after_constraint",
        prompt="Je voyage de mercredi a vendredi, adapte si besoin",
        expectation="coherent_commit_or_pending",
        description="extended availability probe: new availability after broad constraint should stay coherent.",
        followups=("Finalement vendredi matin je peux m'entrainer",),
    ),
    SmokeScenario(
        name="why_this_workout",
        prompt="Pourquoi tu m'as mis cette seance de fractionne mercredi ?",
        expectation="no_plan_write",
        description="extended read-only probe: workout explanation should not write.",
    ),
    SmokeScenario(
        name="recent_changes_lookup",
        prompt="Qu'est-ce qui a change recemment dans mon plan ?",
        expectation="no_plan_write",
        description="extended read-only probe: recent adaptation lookup should not write.",
    ),
    SmokeScenario(
        name="protect_week_lookup",
        prompt="Qu'est-ce qu'on doit proteger cette semaine ?",
        expectation="no_plan_write",
        description="extended read-only probe: week priority explanation should not mutate.",
    ),
    SmokeScenario(
        name="elliptical_friday_morning",
        prompt="vendredi matin",
        expectation="no_plan_write",
        description="extended elliptical probe: orphan slot fragment should clarify, not mutate.",
    ),
    SmokeScenario(
        name="elliptical_prefer_bike",
        prompt="plutot velo",
        expectation="no_plan_write",
        description="extended elliptical probe: orphan sport preference should clarify or store memory only.",
    ),
    SmokeScenario(
        name="elliptical_cancel",
        prompt="non laisse tomber",
        expectation="no_plan_write",
        description="extended elliptical probe: cancel fragment should close without planning writes.",
    ),
    SmokeScenario(
        name="memory_goal_update",
        prompt="Mon objectif prioritaire devient de finir le 10 km sans exploser",
        expectation="no_plan_write",
        description="extended memory probe: goal update should not create planning writes.",
    ),
    SmokeScenario(
        name="memory_equipment_constraint",
        prompt="Je n'ai plus acces au home trainer cette semaine",
        expectation="no_plan_write",
        description="extended memory probe: equipment constraint without adapt request should not mutate.",
    ),
)


@dataclass(frozen=True)
class GeneratedWeekWorkflow:
    name: str
    payload: dict[str, Any]
    regenerations: int = 2


GENERATED_WEEK_WORKFLOWS: tuple[GeneratedWeekWorkflow, ...] = (
    GeneratedWeekWorkflow(
        name="onboard_loaded_running",
        payload={
            "name": "Loic",
            "primary_objective": "preparer un 10 km propre dans 8 semaines sans casser la recuperation",
            "sports": ["course", "velo", "natation", "renforcement"],
            "weekly_structure_notes": (
                "Mardi possible court, mercredi qualite si frais, jeudi charge pro, "
                "samedi long possible, dimanche famille."
            ),
            "constraints": [
                "fatigue moyenne depuis deux jours",
                "douleur mollet gauche legere si intensite trop proche",
                "pas de natation jeudi",
            ],
            "preferences": ["courir le matin", "garder une vraie journee legere apres qualite"],
            "goal_context": "Objectif principal course, sports secondaires utiles mais pas prioritaires.",
            "current_state_notes": "Forme correcte, pas envie de charger trop vite.",
            "coach_name": "Aster",
            "coach_style": "direct",
            "coach_relationship": "coach lucide et fiable",
            "coach_do": "proteger les seances cles et expliquer les compromis",
            "coach_dont": "empiler du dur pour remplir la semaine",
            "coach_soul": "sobre et precis",
            "timezone": "Europe/Paris",
        },
        regenerations=2,
    ),
    GeneratedWeekWorkflow(
        name="onboard_triathlon_fragile",
        payload={
            "name": "Camille",
            "primary_objective": "reprendre triathlon sprint avec priorite endurance facile",
            "sports": ["natation", "velo", "course", "renforcement"],
            "weekly_structure_notes": (
                "Piscine lundi et vendredi seulement, velo possible mercredi, "
                "course courte samedi, dimanche repos familial."
            ),
            "constraints": [
                "retour apres rhume",
                "pas deux seances dures consecutives",
                "temps limite a 45 minutes en semaine",
            ],
            "preferences": ["seances simples", "technique natation avant volume"],
            "goal_context": "Reprendre proprement avant de chercher la performance.",
            "current_state_notes": "Cardio ok mais fatigue post-maladie a surveiller.",
            "coach_name": "Aster",
            "coach_style": "calme",
            "coach_relationship": "coach protecteur mais clair",
            "coach_do": "privilegier progressivite et recuperation",
            "coach_dont": "prescrire du seuil si le contexte sante est fragile",
            "coach_soul": "pose et net",
            "timezone": "Europe/Paris",
        },
        regenerations=1,
    ),
)

_PENDING_OR_BLOCKED_MODES = {
    "plan_patch_confirmation",
    "mutation_confirmation",
    "plan_patch_blocked",
    "mutation_blocked",
    "pending_accepted",
    "pending_accept_blocked",
}
_CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS = frozenset(
    {
        "move_easy_then_confirm",
        "swap_by_day",
        "move_hard_close",
        "add_hard_dense",
        "add_hard_tomorrow_loaded",
        "fatigue_keep_light",
        "trip_constraint",
        "pending_modify_saturday",
        "pending_ok_accept",
        "replace_swim_with_bike",
        "swim_unavailable_two_weeks_human",
        "swim_unavailable_two_weeks",
    }
)
_MUTATION_CLAIM_MARKERS = (
    "echange fait",
    "swap fait",
    "deplacement fait",
    "remplacement fait",
    "changement fait",
    "c'est deplace",
    "c est deplace",
    "je l'ai deplace",
    "j ai deplace",
    "c'est remplace",
    "c est remplace",
    "j'ai remplace",
    "j ai remplace",
    "c'est cale",
    "c est cale",
    "j'ai cale",
    "j ai cale",
    "c'est ajoute",
    "c est ajoute",
    "j'ai ajoute",
    "j ai ajoute",
    "modification appliquee",
    "changement applique",
    "je l'ai mis",
    "j ai mis",
)
_INTERNAL_JARGON_MARKERS = (
    "content:",
    "response_mode",
    "plan_patch",
    "candidate_id",
    "tool_result",
    "json",
    "runtime",
    "fallback",
    "commit event",
    "candidate backend",
    "candidate possible",
    "pas une reponse finale",
)


def evaluate_scenario_result(
    scenario: SmokeScenario,
    before: DbSnapshot,
    after: DbSnapshot,
) -> ScenarioCheckResult:
    reasons: list[str] = []
    warnings: list[str] = []
    event_delta = _row_delta(before.events, after.events)
    pending_delta = _row_delta(before.pending, after.pending)
    latest_turn = after.latest_turn or {}
    response_mode = str(latest_turn.get("response_mode") or "")
    assistant_message = str(latest_turn.get("assistant_message") or "")
    mutation_applied = bool(latest_turn.get("mutation_applied"))
    pending_confirmation = bool(latest_turn.get("pending_confirmation"))
    new_pending = _new_rows(before.pending, after.pending)
    if _contains_bracket_placeholder(assistant_message):
        warnings.append("assistant reply contains bracket placeholder")
    if _contains_internal_jargon(assistant_message):
        reasons.append("assistant reply leaks internal jargon")
    reasons.extend(_unclassified_legacy_fallback_reasons(after.turns))
    if _canonical_planning_guard_enabled():
        active_pending = _active_pending_rows(after)
        if len(active_pending) > 1:
            reasons.append("duplicate_pending")
        if scenario.name == "confirm_without_pending" and (event_delta or pending_delta or mutation_applied):
            reasons.append("confirm_without_pending wrote planning artifact")
        if scenario.name == "move_easy_then_confirm" and scenario.followups:
            if pending_delta > 1:
                reasons.append("duplicate_pending")
            if mutation_applied and not event_delta:
                reasons.append("pending acceptance marked mutation_applied without event")
    if (
        _canonical_planning_provider_enabled()
        and scenario.name in _CANONICAL_PLANNING_PROVIDER_REQUIRED_SCENARIOS
    ):
        if not _has_canonical_planning_handled_trace(after.turns):
            reasons.append("canonical planning provider did not handle supported planning turn")
        if scenario.followups and after.pending and not _has_canonical_pending_handled_trace(after.turns):
            reasons.append("canonical pending provider did not handle supported pending confirmation")

    if scenario.expectation == "guarded_no_commit":
        if event_delta:
            reasons.append(f"wrote {event_delta} plan mutation event")
        if mutation_applied:
            reasons.append("latest turn marked mutation_applied")
        if new_pending and not any(str(row.get("mutation_type") or "") == "plan_patch" for row in new_pending):
            reasons.append("created pending confirmation outside plan_patch")
        if not event_delta and _looks_like_mutation_claim(assistant_message):
            reasons.append("assistant claimed a mutation without committed event")
        if (
            not event_delta
            and not pending_delta
            and not pending_confirmation
            and response_mode not in _PENDING_OR_BLOCKED_MODES
            and _looks_like_mutation_claim(assistant_message)
        ):
            reasons.append("assistant claimed a mutation without event or pending confirmation")

    elif scenario.expectation == "no_plan_write":
        if event_delta:
            reasons.append(f"wrote {event_delta} plan mutation event")
        if pending_delta:
            reasons.append(f"created {pending_delta} pending confirmation")
        if mutation_applied:
            reasons.append("latest turn marked mutation_applied")
        if _looks_like_mutation_claim(assistant_message):
            reasons.append("assistant claimed a planning mutation on a no-write scenario")

    elif scenario.expectation == "coherent_commit_or_pending":
        if mutation_applied and not event_delta:
            reasons.append("latest turn marked mutation_applied without plan mutation event")
        if not event_delta and not pending_delta and not pending_confirmation:
            if _looks_like_mutation_claim(assistant_message):
                reasons.append("assistant claimed a mutation without event or pending confirmation")

    else:
        reasons.append(f"unknown expectation {scenario.expectation!r}")

    return ScenarioCheckResult(ok=not reasons, reasons=reasons, warnings=warnings)


def evaluate_generated_week_response(
    name: str,
    response: dict[str, Any],
    snapshot: DbSnapshot,
) -> ScenarioCheckResult:
    week = response.get("week_plan") if isinstance(response.get("week_plan"), dict) else response
    days = week.get("days") if isinstance(week, dict) else None
    reasons: list[str] = []
    warnings: list[str] = []

    if not isinstance(days, list):
        reasons.append("response has no week days")
        days = []
    elif len(days) != 7:
        reasons.append(f"response has {len(days)} day(s), expected 7")

    active_days = [day for day in days if isinstance(day, dict) and _is_active_training_day(day)]
    if not active_days:
        reasons.append("response has no active training day")
    for day in active_days:
        if not str(day.get("session_description") or "").strip():
            reasons.append(f"active day {day.get('day') or '?'} has no session description")
            break

    if not snapshot.sessions:
        reasons.append("created no scheduled sessions")
    active_sessions = [row for row in snapshot.sessions if _is_active_training_day(row)]
    if snapshot.sessions and not active_sessions:
        reasons.append("created only rest scheduled sessions")

    hard_sessions = [row for row in active_sessions if _is_hard_session(row)]
    if len(hard_sessions) > 3:
        reasons.append(f"created {len(hard_sessions)} hard scheduled sessions")
    min_hard_gap = _min_session_gap_hours(hard_sessions)
    if min_hard_gap is not None and min_hard_gap < 36:
        reasons.append(f"hard scheduled sessions too close: {min_hard_gap:.1f}h")

    if snapshot.events:
        reasons.append(f"created {len(snapshot.events)} plan mutation event(s)")
    if snapshot.pending:
        reasons.append(f"created {len(snapshot.pending)} pending confirmation(s)")

    summary = str(week.get("summary") or "") if isinstance(week, dict) else ""
    if "fallback sportif" in summary.lower():
        warnings.append(f"{name} used generated-week fallback")

    return ScenarioCheckResult(ok=not reasons, reasons=reasons, warnings=warnings)


def _row_delta(before_rows: tuple[dict[str, Any], ...], after_rows: tuple[dict[str, Any], ...]) -> int:
    return len(_new_rows(before_rows, after_rows))


def _canonical_planning_provider_enabled() -> bool:
    raw = os.getenv("FITMAS_CANONICAL_PLANNING_PROVIDER")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _canonical_planning_guard_enabled() -> bool:
    return _canonical_planning_provider_enabled()


def _has_canonical_planning_handled_trace(turns: tuple[dict[str, Any], ...]) -> bool:
    for row in turns:
        context = _turn_context(row)
        provider = context.get("canonical_planning_provider")
        legacy = context.get("legacy_decide")
        if isinstance(provider, dict) and isinstance(legacy, dict):
            if provider.get("result") == "handled" and legacy.get("legacy_skipped") is True:
                return True
    return False


def _has_canonical_pending_handled_trace(turns: tuple[dict[str, Any], ...]) -> bool:
    for row in turns:
        context = _turn_context(row)
        provider = context.get("canonical_pending_provider")
        if isinstance(provider, dict) and provider.get("result") == "handled":
            return True
    return False


def _unclassified_legacy_fallback_reasons(turns: tuple[dict[str, Any], ...]) -> list[str]:
    try:
        if str(BACKEND_SRC) not in sys.path:
            sys.path.insert(0, str(BACKEND_SRC))
        from fitmas.decision.fallback_census import (
            unclassified_legacy_fallback_reasons as check_turn_context,
        )
    except Exception:
        return ["fallback_census_import_failed"]

    reasons: list[str] = []
    for row in turns:
        try:
            row_reasons = check_turn_context(_turn_context(row))
        except Exception:
            return ["fallback_census_runtime_failed"]
        for reason in row_reasons:
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def _fallback_census_for_scenario(
    scenario: SmokeScenario,
    result: ScenarioCheckResult,
    snapshot: DbSnapshot,
) -> dict[str, Any]:
    turn_reports: list[dict[str, Any]] = []
    owner_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for row in snapshot.turns:
        context = _turn_context(row)
        entries = _fallback_entries_for_context(context)
        unclassified = _unclassified_legacy_fallback_reasons((row,))
        legacy_decide = context.get("legacy_decide")
        adaptation_candidate_flow = context.get("adaptation_candidate_flow")
        planning_snapshot_flow = context.get("planning_snapshot_flow")
        response_mode = str(row.get("response_mode") or "")
        interesting = (
            bool(entries)
            or bool(unclassified)
            or isinstance(adaptation_candidate_flow, dict)
            or isinstance(planning_snapshot_flow, dict)
            or _is_active_legacy_decide(legacy_decide)
            or response_mode.startswith("plan_adaptation_")
            or response_mode
            in {
                "availability_no_affected_session",
                "legacy_decision_contract_disabled",
            }
        )
        if not interesting:
            continue
        for entry in entries:
            owner = str(entry.get("owner") or "unknown")
            source = str(entry.get("source") or "unknown")
            owner_counts[owner] = owner_counts.get(owner, 0) + 1
            source_counts[source] = source_counts.get(source, 0) + 1
        turn_reports.append(
            {
                "turn_id": row.get("id"),
                "response_mode": response_mode,
                "user_message": _excerpt(row.get("user_message")),
                "assistant_message": _excerpt(row.get("assistant_message"), limit=360),
                "fallback_census": entries,
                "unclassified_legacy_fallbacks": unclassified,
                "legacy_decide": legacy_decide if isinstance(legacy_decide, dict) else None,
                "canonical_planning_provider": _dict_or_none(
                    context.get("canonical_planning_provider")
                ),
                "canonical_pending_provider": _dict_or_none(
                    context.get("canonical_pending_provider")
                ),
                "adaptation_candidate_flow": _dict_or_none(adaptation_candidate_flow),
                "planning_snapshot_flow": _dict_or_none(planning_snapshot_flow),
                "canonical_understanding": _canonical_understanding_summary(
                    context.get("canonical_understanding")
                ),
            }
        )
    return {
        "scenario": scenario.name,
        "expectation": scenario.expectation,
        "ok": result.ok,
        "reasons": list(result.reasons),
        "warnings": list(result.warnings),
        "latest_response_mode": (
            str(snapshot.latest_turn.get("response_mode") or "") if snapshot.latest_turn else None
        ),
        "fallback_turn_count": len(turn_reports),
        "owner_counts": owner_counts,
        "source_counts": source_counts,
        "turns": turn_reports,
    }


def _fallback_entries_for_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        if str(BACKEND_SRC) not in sys.path:
            sys.path.insert(0, str(BACKEND_SRC))
        from fitmas.decision.fallback_census import fallback_entries
    except Exception:
        return []
    try:
        return [dict(entry) for entry in fallback_entries(context)]
    except Exception:
        return []


def _is_active_legacy_decide(value: object) -> bool:
    return isinstance(value, dict) and value.get("legacy_skipped") is False


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _canonical_understanding_summary(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "intent": value.get("intent"),
        "confidence": value.get("confidence"),
        "requested_change": _dict_or_none(value.get("requested_change")),
        "requested_change_count": 1 if isinstance(value.get("requested_change"), dict) else 0,
        "signal_count": len(value.get("extracted_signals") or ()),
    }


def _excerpt(value: object, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _write_fallback_census_report(path: Path, reports: list[dict[str, Any]]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "scenario_count": len(reports),
        "fallback_scenario_count": sum(1 for report in reports if report["fallback_turn_count"]),
        "reports": reports,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"fallback census: {path}")


def _turn_context(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("context_json")
    if not raw:
        return {}
    try:
        context = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return context if isinstance(context, dict) else {}


def _active_pending_rows(snapshot: DbSnapshot) -> tuple[dict[str, Any], ...]:
    return tuple(row for row in snapshot.pending if str(row.get("status") or "") == "pending")


def _new_rows(
    before_rows: tuple[dict[str, Any], ...],
    after_rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    before_ids = {row.get("id") for row in before_rows if row.get("id") is not None}
    if before_ids:
        return tuple(row for row in after_rows if row.get("id") not in before_ids)
    if len(after_rows) <= len(before_rows):
        return ()
    return tuple(after_rows[len(before_rows) :])


def _looks_like_mutation_claim(message: str) -> bool:
    if _looks_like_backend_action_claim(message):
        return True
    normalized = _normalize(message)
    return any(marker in normalized for marker in _MUTATION_CLAIM_MARKERS)


def _looks_like_backend_action_claim(message: str) -> bool:
    try:
        if str(BACKEND_SRC) not in sys.path:
            sys.path.insert(0, str(BACKEND_SRC))
        from fitmas.decision.output_verifier import looks_like_action_claim
    except Exception:
        return False
    return looks_like_action_claim(message)


def _contains_bracket_placeholder(message: str) -> bool:
    normalized = _normalize(message)
    placeholders = ("[jour]", "[seance", "[autre", "[sortie", "[session")
    return any(marker in normalized for marker in placeholders)


def _contains_internal_jargon(message: str) -> bool:
    normalized = _normalize(message)
    return any(marker in normalized for marker in _INTERNAL_JARGON_MARKERS)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.lower().split())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real HTTP + real LLM A+ WeekCoherence smoke scenarios."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in (*SCENARIOS, *DAILY_SCENARIOS, *EXTENDED_SCENARIOS)],
        help="Run only this scenario. Repeatable.",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="Run the expanded daily-life conversation battery instead of the A+ core scenario set.",
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Run the extended legacy fallback census battery.",
    )
    parser.add_argument(
        "--generated-workflow",
        action="append",
        choices=[workflow.name for workflow in GENERATED_WEEK_WORKFLOWS],
        help="Run this generated-week onboarding/regenerate workflow. Repeatable.",
    )
    parser.add_argument(
        "--skip-generated-week",
        action="store_true",
        help="Skip generated-week onboarding/regenerate workflows.",
    )
    parser.add_argument("--port", type=int, default=8073, help="First localhost port to try.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=ROOT / f".tmp-smoke-a-plus-api-{os.getpid()}.db",
        help="SQLite DB path for the isolated smoke run.",
    )
    parser.add_argument("--keep-db", action="store_true", help="Keep the smoke DB after the run.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for each real API call.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the local API to become healthy.",
    )
    parser.add_argument(
        "--fallback-census-json",
        type=Path,
        help="Write a JSON report of legacy fallback/candidate usage per scenario.",
    )
    args = parser.parse_args(argv)
    if args.daily and args.extended:
        parser.error("--daily and --extended are mutually exclusive")
    return args


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv or sys.argv[1:])
    db_path = args.db_path.resolve()
    selected = _selected_scenarios(
        args.scenario,
        include_daily=args.daily,
        include_extended=args.extended,
    )
    selected_generated = _selected_generated_workflows(
        args.generated_workflow,
        include_default=(
            not args.scenario
            and not args.daily
            and not args.extended
            and not args.skip_generated_week
        ),
    )
    port = _choose_port(args.port)
    base_url = f"http://127.0.0.1:{port}"
    log_path = ROOT / f".tmp-smoke-a-plus-api-{os.getpid()}.log"

    os.environ["FITMAS_DB_PATH"] = str(db_path)
    os.environ.setdefault("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", "1")
    if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]

    print(
        "A+ API smoke: "
        f"{len(selected)} message scenario(s), "
        f"{len(selected_generated)} generated-week workflow(s)"
    )
    print(f"DB: {db_path}")
    print(f"API: {base_url}")
    print(f"log: {log_path}")
    print("")

    _reset_and_seed_database(db_path)
    server, log_file = _start_server(port=port, db_path=db_path, log_path=log_path)
    try:
        _wait_for_health(base_url, timeout_seconds=args.startup_timeout)
        failures = 0
        checks = 0
        fallback_census_reports: list[dict[str, Any]] = []
        for scenario in selected:
            _reset_and_seed_database(db_path)
            before = load_db_snapshot(db_path)
            checks += 1
            print(f"SCENARIO {scenario.name}")
            print(f"prompt: {scenario.prompt}")
            try:
                messages = (scenario.prompt, *scenario.followups)
                for index, message in enumerate(messages, start=1):
                    if len(messages) > 1:
                        print(f"turn#{index}: {message}")
                    response = _post_message(base_url, message, timeout_seconds=args.timeout)
                    assistant_text = _assistant_text_from_response(response)
                    print(f"assistant: {assistant_text}")
            except Exception as exc:  # pragma: no cover - exercised by real smoke only
                failures += 1
                print(f"FAIL: HTTP/LLM error: {exc}")
                print("")
                continue

            after = load_db_snapshot(db_path)
            result = evaluate_scenario_result(scenario, before, after)
            fallback_census_reports.append(_fallback_census_for_scenario(scenario, result, after))
            _print_artifacts(before, after)
            if result.ok:
                print("OK")
            else:
                failures += 1
                print("FAIL")
                for reason in result.reasons:
                    print(f"- {reason}")
            for warning in result.warnings:
                print(f"WARN: {warning}")
            print("")

        for workflow in selected_generated:
            failures, checks = _run_generated_week_workflow(
                workflow,
                base_url=base_url,
                db_path=db_path,
                timeout_seconds=args.timeout,
                failures=failures,
                checks=checks,
            )

        if args.fallback_census_json:
            _write_fallback_census_report(args.fallback_census_json, fallback_census_reports)

        if failures:
            print(f"RESULT: FAIL ({failures}/{checks} check(s))")
            print(f"server log: {log_path}")
            return 1
        print(f"RESULT: OK ({checks} check(s))")
        return 0
    finally:
        _stop_server(server)
        log_file.close()
        if not args.keep_db:
            _unlink_if_exists(db_path)
        _unlink_if_exists(db_path.with_suffix(db_path.suffix + "-journal"))


def _selected_scenarios(
    names: list[str] | None,
    *,
    include_daily: bool = False,
    include_extended: bool = False,
) -> tuple[SmokeScenario, ...]:
    available = (*SCENARIOS, *DAILY_SCENARIOS, *EXTENDED_SCENARIOS)
    if not names:
        if include_extended:
            return EXTENDED_SCENARIOS
        return DAILY_SCENARIOS if include_daily else SCENARIOS
    by_name = {scenario.name: scenario for scenario in available}
    return tuple(by_name[name] for name in names)


def _selected_generated_workflows(
    names: list[str] | None,
    *,
    include_default: bool,
) -> tuple[GeneratedWeekWorkflow, ...]:
    if not names:
        return GENERATED_WEEK_WORKFLOWS if include_default else ()
    by_name = {workflow.name: workflow for workflow in GENERATED_WEEK_WORKFLOWS}
    return tuple(by_name[name] for name in names)


def _run_generated_week_workflow(
    workflow: GeneratedWeekWorkflow,
    *,
    base_url: str,
    db_path: Path,
    timeout_seconds: float,
    failures: int,
    checks: int,
) -> tuple[int, int]:
    _reset_database_schema(db_path)
    print(f"GENERATED_WEEK {workflow.name}")
    try:
        response = _post_json(
            base_url,
            "/api/v0/onboard",
            workflow.payload,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # pragma: no cover - exercised by real smoke only
        print(f"FAIL: onboard HTTP/LLM error: {exc}")
        print("")
        return failures + 1, checks + 1

    checks += 1
    snapshot = load_db_snapshot(db_path)
    result = evaluate_generated_week_response(f"{workflow.name}:onboard", response, snapshot)
    _print_generated_week_artifacts("onboard", response, snapshot)
    failures = _print_check_result(result, failures)

    for index in range(1, workflow.regenerations + 1):
        try:
            response = _post_json(
                base_url,
                "/api/v0/week/regenerate",
                {},
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - exercised by real smoke only
            checks += 1
            failures += 1
            print(f"FAIL: regenerate#{index} HTTP/LLM error: {exc}")
            print("")
            continue
        checks += 1
        snapshot = load_db_snapshot(db_path)
        result = evaluate_generated_week_response(f"{workflow.name}:regenerate#{index}", response, snapshot)
        _print_generated_week_artifacts(f"regenerate#{index}", response, snapshot)
        failures = _print_check_result(result, failures)
    print("")
    return failures, checks


def _print_check_result(result: ScenarioCheckResult, failures: int) -> int:
    if result.ok:
        print("OK")
    else:
        failures += 1
        print("FAIL")
        for reason in result.reasons:
            print(f"- {reason}")
    for warning in result.warnings:
        print(f"WARN: {warning}")
    return failures


def _choose_port(start_port: int) -> int:
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"no free localhost port from {start_port} to {start_port + 49}")


def _start_server(
    *,
    port: int,
    db_path: Path,
    log_path: Path,
) -> tuple[subprocess.Popen[bytes], Any]:
    env = os.environ.copy()
    env["FITMAS_DB_PATH"] = str(db_path)
    env.setdefault("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", "1")
    if not env.get("ANTHROPIC_API_KEY") and env.get("DEEPSEEK_API_KEY"):
        env["ANTHROPIC_API_KEY"] = env["DEEPSEEK_API_KEY"]
    log_file = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--app-dir",
            str(BACKEND_SRC),
            "fitmas.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return process, log_file


def _wait_for_health(base_url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - timing dependent
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"API did not become healthy: {last_error}")


def _post_message(base_url: str, prompt: str, *, timeout_seconds: float) -> dict[str, Any]:
    return _post_json(base_url, "/api/v0/messages", {"text": prompt}, timeout_seconds=timeout_seconds)


def _post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _assistant_text_from_response(response: dict[str, Any]) -> str:
    message = response.get("assistant_message")
    if isinstance(message, dict):
        return str(message.get("text") or "")
    return str(message or "")


def _print_artifacts(before: DbSnapshot, after: DbSnapshot) -> None:
    event_delta = _row_delta(before.events, after.events)
    pending_delta = _row_delta(before.pending, after.pending)
    latest_turn = after.latest_turn or {}
    session_changes = _session_changes(before.sessions, after.sessions)
    print(
        "artifacts: "
        f"events=+{event_delta} "
        f"pending=+{pending_delta} "
        f"mode={latest_turn.get('response_mode') or '-'} "
        f"mutation_applied={bool(latest_turn.get('mutation_applied'))} "
        f"session_changes={len(session_changes)}"
    )
    for row in _new_rows(before.events, after.events):
        print(f"  event#{row.get('id')}: {row.get('command_type') or '-'} {row.get('target_session_ids_json') or ''}")
    for row in _new_rows(before.pending, after.pending):
        print(f"  pending#{row.get('id')}: {row.get('mutation_type') or '-'} {row.get('reason') or ''}")
    for change in session_changes:
        print(f"  session#{change['id']}: {change['before']} -> {change['after']}")


def _print_generated_week_artifacts(label: str, response: dict[str, Any], snapshot: DbSnapshot) -> None:
    week = response.get("week_plan") if isinstance(response.get("week_plan"), dict) else response
    days = week.get("days") if isinstance(week, dict) else []
    active_days = [day for day in days if isinstance(day, dict) and _is_active_training_day(day)]
    hard_sessions = [row for row in snapshot.sessions if _is_active_training_day(row) and _is_hard_session(row)]
    print(
        f"{label}: "
        f"days={len(days) if isinstance(days, list) else '-'} "
        f"active_days={len(active_days)} "
        f"scheduled_sessions={len(snapshot.sessions)} "
        f"hard_sessions={len(hard_sessions)} "
        f"min_hard_gap={_format_gap(_min_session_gap_hours(hard_sessions))}"
    )
    summary = str(week.get("summary") or "") if isinstance(week, dict) else ""
    if summary:
        print(f"  summary: {summary[:180]}")


def _session_changes(
    before_rows: tuple[dict[str, Any], ...],
    after_rows: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    before = {row.get("id"): row for row in before_rows}
    changes: list[dict[str, Any]] = []
    for row in after_rows:
        row_id = row.get("id")
        old = before.get(row_id)
        if old is None:
            changes.append({"id": row_id, "before": "<new>", "after": _session_summary(row)})
        elif _session_summary(old) != _session_summary(row):
            changes.append({"id": row_id, "before": _session_summary(old), "after": _session_summary(row)})
    return changes


def _session_summary(row: dict[str, Any]) -> str:
    return (
        f"{row.get('scheduled_date') or '-'} | "
        f"{row.get('session_title') or '-'} | "
        f"{row.get('sport_type') or '-'} | "
        f"{row.get('session_type') or '-'} | "
        f"{row.get('intensity') or '-'} | "
        f"{row.get('completion_status') or '-'}"
    )


def _is_active_training_day(payload: dict[str, Any]) -> bool:
    sport = str(payload.get("sport_type") or "").strip().lower()
    return sport not in {"", "rest", "off"}


def _is_hard_session(payload: dict[str, Any]) -> bool:
    intensity = str(payload.get("intensity") or "").strip().lower()
    session_type = str(payload.get("session_type") or "").strip().lower()
    return intensity == "hard" or session_type in {"threshold", "intervals", "tempo", "long"}


def _min_session_gap_hours(sessions: list[dict[str, Any]]) -> float | None:
    dates = sorted(parsed for row in sessions if (parsed := _parse_datetime(row.get("scheduled_date"))) is not None)
    if len(dates) < 2:
        return None
    gaps = [
        (later - earlier).total_seconds() / 3600
        for earlier, later in zip(dates, dates[1:])
    ]
    return min(gaps) if gaps else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _format_gap(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}h"


def load_db_snapshot(db_path: Path) -> DbSnapshot:
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return DbSnapshot(
            events=_fetch_all(
                connection,
                """
                select id, source, trigger_type, command_type, target_session_ids_json,
                       user_visible_summary, created_at
                from plan_mutation_events
                order by id
                """,
            ),
            pending=_fetch_all(
                connection,
                """
                select id, status, reason, mutation_type, summary, decision_json, created_at
                from pending_mutation_confirmations
                order by id
                """,
            ),
            sessions=_fetch_all(
                connection,
                """
                select id, scheduled_date, day, session_title, sport_type, session_type,
                       intensity, duration_min, priority, completion_status
                from scheduled_sessions
                order by id
                """,
            ),
            latest_turn=_fetch_one(
                connection,
                """
                select id, user_message, assistant_message, response_mode, mutation_type,
                       mutation_applied, pending_confirmation, pending_confirmation_id,
                       context_json, created_at
                from conversation_turns
                order by id desc
                limit 1
                """,
            ),
            turns=_fetch_all(
                connection,
                """
                select id, user_message, assistant_message, response_mode, mutation_type,
                       mutation_applied, pending_confirmation, pending_confirmation_id,
                       context_json, created_at
                from conversation_turns
                order by id
                """,
            ),
        )


def _fetch_all(connection: sqlite3.Connection, query: str) -> tuple[dict[str, Any], ...]:
    try:
        rows = connection.execute(query).fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(_row_to_dict(row) for row in rows)


def _fetch_one(connection: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    try:
        row = connection.execute(query).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return _row_to_dict(row)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("mutation_applied", "pending_confirmation"):
        if key in result:
            result[key] = bool(result[key])
    return result


def _reset_and_seed_database(db_path: Path) -> None:
    _reset_database_schema(db_path)

    from fitmas.core import orm as s
    from fitmas.core.db import SessionLocal
    from fitmas.core.time_context import DAY_KEYS, day_label_fr, get_local_now
    from fitmas.domain.execution import repository as execution_repo

    with SessionLocal() as db:
        user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            age=31,
            primary_objective="10 km propre sans casser la semaine",
            objective="10 km propre sans casser la semaine",
            weekly_structure_notes=(
                "Mercredi qualite course, jeudi sortie longue, vendredi recuperation, "
                "samedi velo facile, dimanche natation."
            ),
            coach_name="Aster",
            coach_style="direct",
            coach_relationship="lucide et stable",
            coach_do="proteger les seances cles et la recuperation",
            coach_dont="committer un compromis sportif fragile sans confirmation",
            coach_soul="sobre, precis, fiable",
            onboarding_status="completed",
        )
        db.add(user)
        db.flush()
        for rank, sport in enumerate(("running", "cycling", "swimming", "strength")):
            db.add(s.UserSport(user_id=user.id, sport_type=sport, priority_rank=rank, active=True))
        db.add(s.UserPreference(user_id=user.id, text="matin > soir"))
        db.add(s.UserConstraint(user_id=user.id, text="semaine deja dense, proteger la recuperation"))
        db.add(
            s.UserFact(
                user_id=user.id,
                category="training_state",
                key="current_state",
                value="forme correcte mais charge recente moderee, pas de double intensite inutile",
                source="a_plus_smoke",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="medium",
                affects_json='["planning","conversation","heartbeat"]',
            )
        )

        now = get_local_now(user.timezone)
        wednesday = _next_weekday_date(now, target_weekday=2)
        sessions = (
            _session_payload(
                s,
                user_id=user.id,
                target=wednesday.replace(hour=8, minute=0, second=0, microsecond=0),
                title="Fractionne seuil",
                sport_type="running",
                session_type="threshold",
                intensity="hard",
                duration_min=65,
                priority="Seance cle",
                goal="Stimulus course principal",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0),
                title="Sortie longue cle",
                sport_type="running",
                session_type="long",
                intensity="hard",
                duration_min=95,
                priority="Seance cle",
                goal="Endurance specifique",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=2)).replace(hour=8, minute=0, second=0, microsecond=0),
                title="Recuperation mobilite",
                sport_type="strength",
                session_type="recovery",
                intensity="easy",
                duration_min=30,
                priority="Support",
                goal="Absorber la charge",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0),
                title="Velo facile",
                sport_type="cycling",
                session_type="easy",
                intensity="easy",
                duration_min=50,
                priority="Support",
                goal="Aerobie douce",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=4)).replace(hour=9, minute=0, second=0, microsecond=0),
                title="Natation technique",
                sport_type="swimming",
                session_type="easy",
                intensity="easy",
                duration_min=40,
                priority="Support",
                goal="Technique sans fatigue",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
        )
        db.add_all(sessions)
        db.commit()

        for sport_type, title, duration_min, days_ago, tss in (
            ("running", "Footing controle", 45, 3, 32.0),
            ("cycling", "Endurance velo", 70, 6, 38.0),
            ("running", "Tempo propre", 55, 9, 48.0),
        ):
            execution_repo.add_activity(
                db,
                user_id=user.id,
                source="manual",
                scheduled_session_id=None,
                sport_type=sport_type,
                title=title,
                duration_min=duration_min,
                distance_m=0,
                elevation_m=0,
                perceived_load=3,
                note="a_plus_smoke",
                started_at=now - timedelta(days=days_ago),
                matched_day=None,
                match_reason="a_plus_smoke",
                tss=tss,
            )


def _reset_database_schema(db_path: Path) -> None:
    os.environ["FITMAS_DB_PATH"] = str(db_path)
    if str(BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(BACKEND_SRC))

    from fitmas.core.db import Base, engine, init_db

    db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()


def _next_weekday_date(now: datetime, *, target_weekday: int) -> datetime:
    delta = (target_weekday - now.weekday()) % 7
    if delta == 0:
        delta = 7
    return now + timedelta(days=delta)


def _session_payload(
    schema_module: Any,
    *,
    user_id: int,
    target: datetime,
    title: str,
    sport_type: str,
    session_type: str,
    intensity: str,
    duration_min: int,
    priority: str,
    goal: str,
    day_keys: list[str],
    day_label_fr: Any,
    source_plan_created_at: datetime,
) -> Any:
    day_key = day_keys[target.weekday()]
    return schema_module.ScheduledSession(
        user_id=user_id,
        day=day_key,
        label=day_label_fr(day_key, capitalize=True),
        scheduled_date=target.replace(tzinfo=None),
        source_plan_created_at=source_plan_created_at.replace(tzinfo=None),
        sport_type=sport_type,
        session_type=session_type,
        session_title=title,
        session_goal=goal,
        session_note="smoke A+",
        session_description=f"{duration_min} min",
        duration_min=duration_min,
        intensity=intensity,
        load_score=5 if intensity == "hard" else 2,
        priority=priority,
        nutrition_focus="",
        flexibility="stable" if priority == "Seance cle" else "flexible",
        completion_status="planned",
    )


def _stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:  # pragma: no cover - timing dependent
        process.kill()
        process.wait(timeout=5)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
