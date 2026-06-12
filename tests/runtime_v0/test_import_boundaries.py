from pathlib import Path


FORBIDDEN = (
    "fitmas.legacy.decision",
    "fitmas.legacy.domain",
    "fitmas.legacy.llm",
    "fitmas.legacy.skills",
    "fitmas.legacy.tools",
    "fitmas.legacy.app",
)

ROOT = Path("backend/src/fitmas/runtime_v0")


def _core_files() -> list[Path]:
    """V0 core files only.

    `adapters/` is the legacy bridge: it MAY import the existing product (core
    ORM today, domain writers later) and does not count against the core budget.
    The core is everything else and stays isolated + offline-testable.
    """
    return [
        path
        for path in ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and "adapters" not in path.parts
        and " 2" not in path.name  # ignore macOS/sync duplicate copies ("foo 2.py")
    ]


def test_runtime_v0_core_does_not_import_existing_runtime_layers():
    offenders = []
    for path in _core_files():
        text = path.read_text()
        for forbidden in FORBIDDEN:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                offenders.append(f"{path}: {forbidden}")
    assert offenders == []


def test_runtime_v0_core_does_not_import_adapters():
    # Dependency points one way: adapters -> core, never core -> adapters. The
    # core consumes an isolated v0_* DB; it must never reach into the bridge.
    offenders = []
    for path in _core_files():
        text = path.read_text()
        if (
            "runtime_v0.adapters" in text
            or "from .adapters" in text
            or "from ..adapters" in text
        ):
            offenders.append(str(path))
    assert offenders == []


def test_runtime_v0_core_stays_under_v0_budget():
    # Cap raised 3200 -> 3700 (5 juin 2026): Meso sport engine (meso/), fact
    # resolution, and the fact-rider (note a durable fact + act in one turn).
    # 3700 -> 3720 (5 juin 2026): Slice 2.0 context-pack (ContextPack +
    # build_context_pack + actuals_from_week, voie b forward-only).
    # 3720 -> 3960 (6 juin 2026): Slice 2.1 generator (generator.py, week_generation
    # prompt, constraint-aware relaxation).
    # 3960 -> 4080 (6 juin 2026): Slice 3a propose_week wiring — week_proposal type +
    # WeekProposalDraft (proposals.py), the propose_week handler (meso/runtime_tool.py),
    # ToolContext.generation_llm, tool_catalog registration, policy answer_only branch,
    # RuntimeDeps.generation_llm threading. Real core 4070.
    # Deliberate, planned capability growth, not creep. Bump per real growth only.
    # 4080 -> 4100 (6 juin 2026): Slice 3a couche-2 reliabilization — teach the coach
    # propose_week (coach_system prompt) + surface last-week training in the header
    # (recent_training) so the coach can ground the seed.
    # RE-BASELINE (7 juin 2026, decision Loïc): the pre-3b simplification pass is
    # resolved as a re-baseline, NOT a LOC clawback. meso/ + wiring are already
    # tight — every piece is used or a documented seam (3b / 2.1 / Macro). The Meso
    # engine is a deliberate second envelope: earned capability, not creep (see
    # RUNTIME-V0.md Budget). The ~2500 ideal stays the ratchet for the bare
    # conversational loop; discipline = bump only on proven capability. Slice 3b
    # (confirmation -> commit + typed store + forward chaining) bumps this cap ON
    # LANDING with its real number, not before.
    # 4100 -> 4280 (7 juin 2026): Slice 3b landed — pending_resolution mechanism,
    # resolve_pending tool, v0_planned_weeks store, week commit handler, forward
    # chaining. Proven capability, not creep (see RUNTIME-V0.md Budget).
    # 4280 -> 4300 (7 juin 2026): reliable constrained-week generation — the prompt
    # drops the prescribed hard key when intensity is restricted (réduction-sous-
    # contrainte), and the verifier rejects degenerate empty/all-rest weeks in every
    # mode. Closes the generator/verifier asymmetry. Proven couche 2 (probe_constrained_week
    # 4/4, source=llm, constraint respected, commit ok).
    # 4300 -> 4320 (7 juin 2026): coach taught to resolve a pending correctly — a
    # "oui mais [constraint/injury/indispo]" is NOT a clean accept (note the fact, don't
    # commit the unchanged week). Found by probe_live_simulation (committed a hard week
    # under a fresh injury / claimed false adjustments). Coach-prompt teaching only.
    # 4320 -> 4337 (8 juin 2026): ré-adaptation same-turn sous blessure (tranche #1).
    # propose_week accepte une contrainte déclarée (intensity_restricted) pour
    # re-proposer une semaine sans intensité dans le MÊME tour qu'un "oui mais
    # [blessure]" ; un nouveau pending semaine supersede l'ancien. Ferme le gap
    # "safe mais pas ré-adapté" pour la blessure. Capacité prouvée offline ; couche 2
    # (probe_live_simulation persona blessure) confirme la ré-adaptation réelle.
    # Spec : docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md.
    # 4337 -> 4440 (8 juin 2026): chantier dogfood — (a) #2 availability typée :
    # TypedConstraint.blocked_days + verifier _check_blocked_days/blocked_weekday_indices
    # + relâche du plancher de charge sous jours bloqués (garde la clé) + générateur et
    # template constraint-aware + propose_week(blocked_days) + sous-règle coach indispo ;
    # (b) get_planned_week (lire la semaine committée). Capacité prouvée offline (261 tests) ;
    # couche 2 (probe_live_simulation persona indispo) confirme la ré-adaptation autour des
    # jours bloqués. Le ratchet ~2500 du noyau conversationnel nu reste inchangé (croissance
    # = enveloppe Meso acquise). Spec : docs/superpowers/specs/2026-06-08-v0-dogfood-wiring-design.md.
    # 4440 -> 4496 (8 juin 2026): réconciliation des deux stores de plan — (a) au commit d'une
    # semaine Meso, _materialize_week_sessions la pose sur le calendrier (v0_scheduled_sessions) :
    # remplace le planifié, préserve l'exécuté, saute les rest. Une seule vérité du plan jour ;
    # débloque injury-after-commit, l'exécution et le patch chirurgical sur une semaine générée.
    # (b) sous-règle coach : une blessure signalée alors qu'une semaine est déjà committée (sans
    # pending) re-propose une semaine sans intensité (symétrique du « oui mais [blessure] »).
    # Enveloppe Meso acquise (le pont), pas du noyau conversationnel nu. Prouvé offline
    # (test_executor_week_materialization) ; couche 2 (probe blessure post-commit).
    # Spec : docs/superpowers/specs/2026-06-08-plan-store-reconciliation-design.md.
    # 4496 -> 4505 (9 juin 2026): v0_activities.scheduled_session_id — schema column +
    # _ensure_activity_columns idempotent migration (mirrors _ensure_fact_columns).
    # Foundation for the manual activity<->session link feature (task 1/7).
    # 4505 -> 4571 (9 juin 2026): LinkActivityToSessionCommand + UnlinkActivityCommand —
    # two new executor commands (policy dataclasses + dispatch + _target cases +
    # _activity/_activity_or_raise helpers + handlers). Audited, ownership-checked.
    # Task 2/7 of the manual activity<->session link feature.
    # 4571 -> 4573 (9 juin 2026): sport_mismatch guard in _apply_link_activity_to_session —
    # +2 lines to reject cross-sport links before any write (backstop for bug #1).
    # 4573 -> 4586 (9 juin 2026): rich Strava fields on v0_activities (avg_speed, avg_hr,
    # elevation_m, calories, map_polyline) — schema columns + migration loop in db.py.
    # 4586 -> 4654 (12 juin 2026): mémoire court terme conversationnelle — transcript
    # verbatim des 4 derniers échanges (<=48h) dans le SnapshotHeader, reconstruit
    # read-only depuis v0_input_events x v0_turns (zéro nouvelle table) ; + canal
    # warnings du guard (warn:confirmation_without_pending, jamais bloquant). Motivé
    # par le dogfood du 12 juin (fil de conversation mort à chaque tour). Capacité
    # prouvée couche 2 (probe_live_simulation persona fil, DeepSeek 2/2, juge 5/5/5/5).
    # Spec : docs/superpowers/specs/2026-06-12-mini-transcript-design.md.
    loc = sum(len(path.read_text().splitlines()) for path in _core_files())
    assert loc <= 4654
