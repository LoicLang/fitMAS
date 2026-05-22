"""Snapshot tests for render_digest_for_prompt.

The digest is the coach's pre-composed context for proactive messages and
decide() calls. Its rendering shape is a contract with the downstream LLM:
if it drifts, the coach's voice breaks. These tests pin the rendered string
byte-for-byte on representative fixtures so unintended format churn is
caught immediately.

The lens LLM call is never invoked here — fixtures pass a pre-built
CoachReadingLens to isolate rendering from LLM output variability.
"""
from __future__ import annotations

from fitmas.domain.coaching.coach_reading_digest import (
    CoachReadingDigest,
    CoachReadingFacts,
    CoachReadingLens,
    ExchangeEntry,
    RealEntry,
    render_digest_for_prompt,
)


def _digest(
    *,
    real_entries: tuple[RealEntry, ...] = (),
    planned_total_7d: int = 0,
    confirmed_total_7d: int = 0,
    offplan_total_7d: int = 0,
    missed_streak_days: int = 0,
    silence_days: int = 0,
    exchanges_7d: tuple[ExchangeEntry, ...] = (),
    patterns: tuple[str, ...] = (),
    day_context: str = "lundi, semaine neuve",
    lens: CoachReadingLens | None = None,
) -> CoachReadingDigest:
    facts = CoachReadingFacts(
        real_entries=real_entries,
        planned_total_7d=planned_total_7d,
        confirmed_total_7d=confirmed_total_7d,
        offplan_total_7d=offplan_total_7d,
        missed_streak_days=missed_streak_days,
        silence_days=silence_days,
        exchanges_7d=exchanges_7d,
        patterns=patterns,
        day_context=day_context,
    )
    return CoachReadingDigest(facts=facts, lens=lens)


def test_render_offplan_week_with_lens() -> None:
    digest = _digest(
        real_entries=(
            RealEntry(day_label="lun", sport="running", duration_min=45, linked_to_plan=False),
            RealEntry(day_label="sam", sport="velo", duration_min=90, linked_to_plan=False),
        ),
        planned_total_7d=3,
        confirmed_total_7d=0,
        offplan_total_7d=2,
        missed_streak_days=3,
        silence_days=4,
        exchanges_7d=(
            ExchangeEntry(when_label="mar 14h", speaker="user", text="charge de taf cette semaine, je zappe strength"),
            ExchangeEntry(when_label="mar 14h", speaker="coach", text="ok, on replace jeudi ?"),
            ExchangeEntry(when_label="jeu 19h", speaker="coach", text="tu as pu faire strength ?"),
        ),
        patterns=("Saute souvent la strength, honore le cardio.",),
        lens=CoachReadingLens(
            sens_du_jour="Il a bouge mais pas execute le plan. Le trou c'est strength, 3e semaine.",
            angle="Reconnaitre les 2 sorties, questionner la strength sans juger.",
            ne_pas_faire="dire zero realisees, parler sommeil/assiette, moraliser",
        ),
    )

    expected = (
        "Lecture de la semaine (verite terrain, utilise ces chiffres tels quels) :\n"
        "- Reel 7j : running 45' lun (offplan), velo 90' sam (offplan)\n"
        "- Plan 7j : 3 prevues, 0 executees conformes, 2 sortie(s) hors plan, 3j consecutifs sans seance realisee\n"
        "- Silence user : 4j depuis le dernier message\n"
        "- Derniers echanges (a ne pas recycler ni repeter) :\n"
        '    mar 14h  user  : "charge de taf cette semaine, je zappe strength"\n'
        '    mar 14h  coach  : "ok, on replace jeudi ?"\n'
        '    jeu 19h  coach  : "tu as pu faire strength ?"\n'
        "- Patterns connus :\n"
        "    - Saute souvent la strength, honore le cardio.\n"
        "- Contexte : lundi, semaine neuve\n"
        "\n"
        "Lecture du coach (suis ces trois lignes pour composer le message) :\n"
        "- Sens du jour : Il a bouge mais pas execute le plan. Le trou c'est strength, 3e semaine.\n"
        "- Angle : Reconnaitre les 2 sorties, questionner la strength sans juger.\n"
        "- Ne pas faire : dire zero realisees, parler sommeil/assiette, moraliser"
    )

    assert render_digest_for_prompt(digest) == expected


def test_render_empty_week_without_lens_degrades_gracefully() -> None:
    digest = _digest(
        planned_total_7d=4,
        silence_days=6,
        day_context="lundi, semaine neuve",
        lens=None,
    )
    rendered = render_digest_for_prompt(digest)
    assert "Reel 7j : 0 sortie" in rendered
    assert "4 prevues" in rendered
    assert "Silence user : 6j" in rendered
    # Lens section omitted — no "Sens du jour" line.
    assert "Lecture du coach" not in rendered


def test_render_clean_week_omits_zero_offplan_and_streak() -> None:
    digest = _digest(
        real_entries=(
            RealEntry(day_label="lun", sport="running", duration_min=50, linked_to_plan=True),
            RealEntry(day_label="mer", sport="velo", duration_min=60, linked_to_plan=True),
        ),
        planned_total_7d=4,
        confirmed_total_7d=4,
        offplan_total_7d=0,
        missed_streak_days=0,
        silence_days=2,
        day_context="lundi, semaine neuve",
    )
    rendered = render_digest_for_prompt(digest)
    plan_line = next(line for line in rendered.splitlines() if line.startswith("- Plan 7j"))
    # No "hors plan" fragment when offplan=0, no "Xj consecutifs" when streak=0.
    assert "hors plan" not in plan_line
    assert "consecutifs" not in plan_line
    assert plan_line == "- Plan 7j : 4 prevues, 4 executees conformes"
