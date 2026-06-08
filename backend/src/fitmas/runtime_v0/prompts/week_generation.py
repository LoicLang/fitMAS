"""Prompt for the Meso week generator (Slice 2.1).

The LLM generates ONE running week as a typed skeleton via the emit_week tool. The
verifier judges numbers + enums; the free `detail` prose is the LLM's, never verified.
"""
from __future__ import annotations

from datetime import date, timedelta

from fitmas.runtime_v0.meso.model import ContextPack
from fitmas.runtime_v0.meso.verifier import limits_intensity

GENERATION_SYSTEM = (
    "Tu es un coach de course a pied. Tu generes UNE semaine d'entrainement.\n"
    "Emets la semaine UNIQUEMENT via le tool emit_week (une liste de seances typees) — "
    "aucune prose libre en dehors du champ detail de chaque seance.\n"
    "Respecte la cible: vise la bande de charge et garde le type de seance cle prescrit.\n"
    "EXCEPTION contrainte: si l'intensite est restreinte, la seance cle prescrite SAUTE "
    "cette semaine — aucune seance dure, ni seuil, ni fractionne; remplace-la par du "
    "volume facile (easy, plus une long_run moderate).\n"
    "charge = duree_min x poids (easy=1.0, moderate=1.5, hard=2.0); rest = 0.\n"
    "Si des jours sont bloques (indisponibilite), ne place aucune seance ces jours-la "
    "et reduis le volume en consequence."
)


def render_generation_prompt(pack: ContextPack, week_start: date, mode: str) -> str:
    target = pack.target
    if target is None:
        raise ValueError("render_generation_prompt requires a target (continuity)")
    low, high = target.load_band
    end = week_start + timedelta(days=6)
    relaxed = limits_intensity(pack.constraints)
    lines = [
        f"mode: {mode}",
        f"semaine: {week_start.isoformat()} -> {end.isoformat()} (lundi a dimanche)",
        f"phase: {target.phase}",
    ]
    if relaxed:
        # Constraint-aware: an intensity restriction drops the prescribed hard key
        # this week (réduction-sous-contrainte) — the verifier relaxes the key check
        # in the same case, so generation and verification stay in sync.
        lines.append(
            "seance cle: supprimee cette semaine (intensite restreinte) — volume facile "
            "uniquement, aucune seance dure ni seuil ni fractionne"
        )
    else:
        lines.append(f"seance cle prescrite: {target.key_type}")
    lines += [
        f"bande de charge: {low} a {high}",
        f"progression: {target.progression_axis}",
    ]
    if pack.last_week_actuals is not None:
        lines.append(
            f"semaine passee reelle: charge {pack.last_week_actuals.total_load}, "
            f"cle {pack.last_week_actuals.key_type}"
        )
    if pack.constraints:
        restrictions = sorted({r for c in pack.constraints if c.active for r in c.restricts})
        if restrictions:
            lines.append(f"contraintes actives: restreint {', '.join(restrictions)}")
    blocked = sorted({day for c in pack.constraints if c.active for day in c.blocked_days})
    if blocked:
        lines.append(f"jours bloques (indisponible): {', '.join(blocked)} — ne place AUCUNE seance ces jours-la")
    return "\n".join(lines)
