from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fitmas.athlete_zones import AthleteZones


@dataclass(frozen=True, slots=True)
class SessionTemplate:
    sport_type: str
    session_type: str
    title: str
    goal: str
    watch_title: str
    watch_detail: str
    default_duration_min: int
    intensity: str
    load_score: int


# ---------------------------------------------------------------------------
# Parametric blueprints — structured session descriptions with zone targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepScaling:
    """How reps scale by athlete level and mesocycle week."""
    beginner_reps: int
    intermediate_reps: int
    advanced_reps: int
    cycle_week_delta: int  # +N reps per build week (0 for week1)


@dataclass(frozen=True, slots=True)
class SessionBlock:
    phase: str  # "warmup", "main", "cooldown"
    block_type: str  # "steady", "intervals", "progressive"
    zone: str  # "Z1", "Z2", ..., "Z5"
    duration_min: int | None = None
    reps: int | None = None  # base reps (overridden by scaling)
    rep_distance: str | None = None  # "400m"
    rep_duration: str | None = None  # "3min"
    rest_type: str | None = None  # "trot Z1 1min30", "R20s"
    scaling: RepScaling | None = None


@dataclass(frozen=True, slots=True)
class SessionBlueprint:
    sport_type: str
    session_type: str
    title: str
    goal: str
    target_zone: str  # primary zone
    blocks: tuple[SessionBlock, ...]
    intensity: str
    load_score: int
    watch_title: str
    watch_detail: str


# ---------------------------------------------------------------------------
# Blueprint registry
# ---------------------------------------------------------------------------

_BLUEPRINTS: tuple[SessionBlueprint, ...] = (
    # --- Running ---
    SessionBlueprint(
        "running", "intervals",
        "Fractionne court", "Stimuler la VMA avec recup complete.",
        "Z5",
        (
            SessionBlock("warmup", "progressive", "Z1", duration_min=15),
            SessionBlock("main", "intervals", "Z5", reps=8, rep_distance="400m",
                         rest_type="trot Z1 1min30",
                         scaling=RepScaling(6, 8, 10, 1)),
            SessionBlock("cooldown", "steady", "Z1", duration_min=10),
        ),
        "hard", 3, "Recuperation", "Le lendemain dira si la dose etait juste.",
    ),
    SessionBlueprint(
        "running", "tempo",
        "Tempo soutenu", "Travailler le seuil sans casser la semaine.",
        "Z3",
        (
            SessionBlock("warmup", "progressive", "Z1", duration_min=15),
            SessionBlock("main", "steady", "Z3", duration_min=25),
            SessionBlock("cooldown", "steady", "Z1", duration_min=10),
        ),
        "hard", 3, "Allure", "Reste propre. Pas de sprint inutile.",
    ),
    SessionBlueprint(
        "running", "long",
        "Sortie longue course", "Construire une base d'endurance stable.",
        "Z1",
        (
            SessionBlock("warmup", "steady", "Z1", duration_min=10),
            SessionBlock("main", "steady", "Z2", duration_min=55),
            SessionBlock("cooldown", "steady", "Z1", duration_min=5),
        ),
        "moderate", 3, "Energie", "Ne pars pas trop vite. Garde du jus.",
    ),
    SessionBlueprint(
        "running", "easy",
        "Footing endurance", "Faire du volume souple sans bruit.",
        "Z1",
        (
            SessionBlock("warmup", "steady", "Z1", duration_min=10),
            SessionBlock("main", "steady", "Z1", duration_min=25),
            SessionBlock("cooldown", "steady", "Z1", duration_min=5),
        ),
        "easy", 1, "Regulier", "Le vrai sujet est de finir frais.",
    ),
    SessionBlueprint(
        "running", "fartlek",
        "Fartlek progressif", "Remettre du rythme avec moins de rigidite.",
        "Z2",
        (
            SessionBlock("warmup", "progressive", "Z1", duration_min=10),
            SessionBlock("main", "intervals", "Z3", reps=6, rep_duration="1min",
                         rest_type="2min facile Z1",
                         scaling=RepScaling(5, 6, 8, 1)),
            SessionBlock("cooldown", "steady", "Z1", duration_min=10),
        ),
        "moderate", 2, "Ressenti", "Ajuste si les jambes sont lourdes.",
    ),
    SessionBlueprint(
        "running", "recovery",
        "Footing recup", "Faire circuler sans ajouter de dette.",
        "Z1",
        (
            SessionBlock("warmup", "steady", "Z1", duration_min=5),
            SessionBlock("main", "steady", "Z1", duration_min=20),
            SessionBlock("cooldown", "steady", "Z1", duration_min=5),
        ),
        "easy", 1, "Souplesse", "Tu dois finir plus frais qu'au depart.",
    ),
    # --- Cycling ---
    SessionBlueprint(
        "cycling", "sweet_spot",
        "Sweet spot velo", "Monter la puissance durable sans exploser.",
        "Z4",
        (
            SessionBlock("warmup", "progressive", "Z1", duration_min=15),
            SessionBlock("main", "intervals", "Z4", reps=3, rep_duration="15min",
                         rest_type="souple Z1 5min",
                         scaling=RepScaling(2, 3, 4, 0)),
            SessionBlock("cooldown", "steady", "Z1", duration_min=10),
        ),
        "hard", 3, "Gestion", "Ne transforme pas ca en VO2.",
    ),
    SessionBlueprint(
        "cycling", "intervals",
        "Intervalles velo", "Travailler les changements de rythme utiles.",
        "Z6",
        (
            SessionBlock("warmup", "progressive", "Z1", duration_min=15),
            SessionBlock("main", "intervals", "Z6", reps=5, rep_duration="3min",
                         rest_type="souple Z1 3min",
                         scaling=RepScaling(4, 5, 6, 1)),
            SessionBlock("cooldown", "steady", "Z1", duration_min=10),
        ),
        "hard", 3, "Recuperation", "Respecte les recups, sinon coupe une rep.",
    ),
    SessionBlueprint(
        "cycling", "endurance",
        "Sortie velo endurance", "Poser du volume propre et regulier.",
        "Z2",
        (
            SessionBlock("warmup", "progressive", "Z1", duration_min=15),
            SessionBlock("main", "steady", "Z2", duration_min=60),
            SessionBlock("cooldown", "steady", "Z1", duration_min=10),
        ),
        "moderate", 2, "Cadence", "Reste fluide et stable.",
    ),
    SessionBlueprint(
        "cycling", "recovery",
        "Velo recup", "Tourner les jambes et faire redescendre la charge.",
        "Z1",
        (
            SessionBlock("warmup", "steady", "Z1", duration_min=10),
            SessionBlock("main", "steady", "Z1", duration_min=25),
            SessionBlock("cooldown", "steady", "Z1", duration_min=5),
        ),
        "easy", 1, "Souplesse", "Mouline, ne pousse pas.",
    ),
    # --- Swimming ---
    SessionBlueprint(
        "swimming", "css",
        "Natation qualite", "Stimuler la vitesse utile dans l'eau.",
        "Z3",
        (
            SessionBlock("warmup", "steady", "Z1", rep_distance="200m"),
            SessionBlock("main", "intervals", "Z3", reps=6, rep_distance="100m",
                         rest_type="R20s",
                         scaling=RepScaling(5, 6, 8, 1)),
            SessionBlock("main", "intervals", "Z4", reps=4, rep_distance="50m",
                         rest_type="R20s"),
            SessionBlock("cooldown", "steady", "Z1", rep_distance="200m"),
        ),
        "hard", 3, "Technique sous fatigue", "Si le geste se casse, reduis la serie.",
    ),
    SessionBlueprint(
        "swimming", "endurance",
        "Natation endurance", "Construire un volume nage propre.",
        "Z2",
        (
            SessionBlock("warmup", "steady", "Z1", rep_distance="200m"),
            SessionBlock("main", "intervals", "Z2", reps=3, rep_distance="300m",
                         rest_type="R30s",
                         scaling=RepScaling(2, 3, 4, 0)),
            SessionBlock("cooldown", "steady", "Z1", rep_distance="200m"),
        ),
        "moderate", 2, "Glisse", "Ne force pas la frequence.",
    ),
    SessionBlueprint(
        "swimming", "endurance_sets",
        "Natation serie endurance", "Tenir des blocs reguliers sans se crisper.",
        "Z2",
        (
            SessionBlock("warmup", "steady", "Z1", rep_distance="200m"),
            SessionBlock("main", "intervals", "Z2", reps=6, rep_distance="150m",
                         rest_type="R20s",
                         scaling=RepScaling(4, 6, 8, 1)),
            SessionBlock("main", "intervals", "Z3", reps=4, rep_distance="50m",
                         rest_type="R20s"),
            SessionBlock("cooldown", "steady", "Z1", rep_distance="100m"),
        ),
        "moderate", 2, "Regulier", "Garde le meme geste du debut a la fin.",
    ),
    SessionBlueprint(
        "swimming", "technique",
        "Natation technique", "Retrouver appuis et qualite de nage.",
        "Z1",
        (
            SessionBlock("warmup", "steady", "Z1", rep_distance="200m"),
            SessionBlock("main", "intervals", "Z1", reps=4, rep_distance="100m",
                         rest_type="R20s"),
            SessionBlock("main", "intervals", "Z1", reps=4, rep_distance="50m",
                         rest_type="R20s"),
            SessionBlock("cooldown", "steady", "Z1", rep_distance="100m"),
        ),
        "easy", 1, "Amplitude", "Reste long dans l'eau.",
    ),
    SessionBlueprint(
        "swimming", "recovery",
        "Natation souple", "Bouger et delier sans charger.",
        "Z1",
        (
            SessionBlock("warmup", "steady", "Z1", rep_distance="200m"),
            SessionBlock("main", "intervals", "Z1", reps=8, rep_distance="50m",
                         rest_type="R15s"),
            SessionBlock("cooldown", "steady", "Z1", rep_distance="100m"),
        ),
        "easy", 1, "Souplesse", "Respiration calme, geste propre.",
    ),
)

_BLUEPRINT_INDEX: dict[tuple[str, str], SessionBlueprint] = {
    (bp.sport_type, bp.session_type): bp for bp in _BLUEPRINTS
}


def get_blueprint(sport_type: str, session_type: str) -> SessionBlueprint | None:
    return _BLUEPRINT_INDEX.get((sport_type, session_type))


_TEMPLATES: tuple[SessionTemplate, ...] = (
    SessionTemplate("running", "easy", "Footing endurance", "Faire du volume souple sans bruit.", "Régulier", "Le vrai sujet est de finir frais.", 45, "easy", 1),
    SessionTemplate("running", "long", "Sortie longue course", "Construire une base d'endurance stable.", "Énergie", "Ne pars pas trop vite. Garde du jus jusqu'au bout.", 75, "moderate", 3),
    SessionTemplate("running", "tempo", "Tempo course", "Travailler le seuil sans casser la semaine.", "Allure", "Reste propre. Pas de sprint inutile.", 55, "hard", 3),
    SessionTemplate("running", "intervals", "Fractionné court", "Stimuler la vitesse utile avec récup complète.", "Récupération", "Le lendemain dira si la dose était juste.", 55, "hard", 3),
    SessionTemplate("running", "fartlek", "Fartlek progressif", "Remettre du rythme avec moins de rigidité.", "Ressenti", "Ajuste si les jambes sont lourdes.", 50, "moderate", 2),
    SessionTemplate("running", "recovery", "Footing récup", "Faire circuler sans ajouter de dette.", "Souplesse", "Tu dois finir plus frais qu'au départ.", 30, "easy", 1),
    SessionTemplate("cycling", "endurance", "Sortie vélo endurance", "Poser du volume propre et régulier.", "Cadence", "Reste fluide et stable.", 90, "moderate", 2),
    SessionTemplate("cycling", "sweet_spot", "Sweet spot vélo", "Monter la puissance durable sans exploser.", "Gestion", "Ne transforme pas ça en VO2.", 75, "hard", 3),
    SessionTemplate("cycling", "intervals", "Intervalles vélo", "Travailler les changements de rythme utiles.", "Récupération", "Respecte les récups, sinon coupe une rep.", 70, "hard", 3),
    SessionTemplate("cycling", "recovery", "Vélo récup", "Tourner les jambes et faire redescendre la charge.", "Souplesse", "Mouline, ne pousse pas.", 45, "easy", 1),
    SessionTemplate("swimming", "technique", "Natation technique", "Retrouver appuis et qualité de nage.", "Amplitude", "Reste long dans l'eau.", 40, "easy", 1),
    SessionTemplate("swimming", "endurance", "Natation endurance", "Construire un volume nage propre.", "Glisse", "Ne force pas la fréquence.", 55, "moderate", 2),
    SessionTemplate("swimming", "endurance_sets", "Natation série endurance", "Tenir des blocs réguliers sans se crisper.", "Régulier", "Garde le même geste du début à la fin.", 50, "moderate", 2),
    SessionTemplate("swimming", "css", "Natation qualité", "Stimuler la vitesse utile dans l'eau.", "Technique sous fatigue", "Si le geste se casse, réduis la série.", 45, "hard", 3),
    SessionTemplate("swimming", "recovery", "Natation souple", "Bouger et délier sans charger.", "Souplesse", "Respiration calme, geste propre.", 30, "easy", 1),
    SessionTemplate("strength", "general", "Renfo général", "Stabiliser le corps sans prendre toute la place.", "Propreté", "Mieux vaut propre que lourd.", 40, "moderate", 2),
    SessionTemplate("strength", "core", "Core et stabilité", "Renforcer la tenue et les appuis.", "Contrôle", "Pas de rep sale en fin de série.", 30, "easy", 1),
    SessionTemplate("strength", "mobility", "Mobilité active", "Rendre les articulations plus disponibles.", "Respiration", "Laisse de la place, ne force pas.", 25, "easy", 1),
    SessionTemplate("climbing", "technique", "Escalade technique", "Prendre de la grimpe utile sans trop de dette.", "Pieds", "Qualité des placements avant tout.", 90, "moderate", 2),
    SessionTemplate("climbing", "bouldering", "Bloc / force", "Stimuler la force et la coordination.", "Avant-bras", "Repos complet entre essais utiles.", 90, "hard", 3),
)


def list_session_templates() -> tuple[SessionTemplate, ...]:
    return _TEMPLATES


def select_session_template(*, sport_type: str, session_type: str) -> SessionTemplate:
    sport_key = (sport_type or "running").strip().lower()
    type_key = (session_type or "easy").strip().lower()
    fallback: SessionTemplate | None = None
    for template in _TEMPLATES:
        if template.sport_type != sport_key:
            continue
        if fallback is None:
            fallback = template
        if template.session_type == type_key:
            return template
    if fallback is not None:
        return fallback
    return next(template for template in _TEMPLATES if template.sport_type == "running" and template.session_type == "easy")


def render_session_description(
    template: SessionTemplate,
    *,
    duration_min: int | None = None,
    zones: AthleteZones | None = None,
    athlete_level: str = "intermediate",
    cycle_week: int = 1,
) -> str:
    """Render session description. Uses blueprint with real zones if available, else legacy text."""
    if zones is not None:
        blueprint = get_blueprint(template.sport_type, template.session_type)
        if blueprint is not None:
            rendered = render_blueprint(
                blueprint, zones,
                duration_min=duration_min or template.default_duration_min,
                athlete_level=athlete_level,
                cycle_week=cycle_week,
            )
            if rendered:
                return rendered
    # Legacy fallback
    resolved_duration = max(10, int(duration_min or template.default_duration_min))
    if template.sport_type == "running":
        return _render_running(template.session_type, duration_min=resolved_duration)
    if template.sport_type == "cycling":
        return _render_cycling(template.session_type, duration_min=resolved_duration)
    if template.sport_type == "swimming":
        return _render_swimming(template.session_type, duration_min=resolved_duration)
    if template.sport_type == "strength":
        return _render_strength(template.session_type, duration_min=resolved_duration)
    if template.sport_type == "climbing":
        return _render_climbing(template.session_type, duration_min=resolved_duration)
    return ""


def _render_running(session_type: str, *, duration_min: int) -> str:
    if session_type == "long":
        main = max(duration_min - 15, 40)
        return f"10min trot lent\n{main}min endurance zone 2 reguliere\n5min marche retour calme"
    if session_type == "tempo":
        main = max(duration_min - 25, 15)
        return f"15min echauffement progressif\n{main}min tempo soutenu mais controle\n10min retour au calme footing lent"
    if session_type == "intervals":
        return "15min echauffement progressif\n8x400m allure 10k recup 1min trot\n10min retour au calme footing lent"
    if session_type == "fartlek":
        main = max(duration_min - 20, 20)
        return f"10min echauffement\n{main}min fartlek 1min vite / 2min facile\n10min retour au calme"
    if session_type == "recovery":
        easy = max(duration_min - 10, 15)
        return f"5min marche active\n{easy}min footing tres facile\n5min retour au calme"
    easy = max(duration_min - 15, 20)
    return f"10min marche/trot\n{easy}min footing zone 2 conversation\n5min retour au calme"


def _render_cycling(session_type: str, *, duration_min: int) -> str:
    if session_type == "sweet_spot":
        bloc = max((duration_min - 25) // 2, 12)
        return f"15min echauffement progressif\n2x{bloc}min sweet spot recup 5min souple\n10min retour au calme"
    if session_type == "intervals":
        return "15min echauffement progressif\n6x3min soutenu recup 3min facile\n10min retour au calme moulinette"
    if session_type == "recovery":
        easy = max(duration_min - 10, 20)
        return f"10min souple\n{easy}min velo facile cadence 90+\n5min retour au calme"
    endurance = max(duration_min - 25, 35)
    return f"15min echauffement progressif\n{endurance}min zone 2 cadence reguliere\n10min retour au calme"


def _render_swimming(session_type: str, *, duration_min: int) -> str:
    if session_type == "css":
        return "200m echauffement souple\n6x100m allure CSS R20s\n4x50m propres et toniques R20s\n200m retour calme"
    if session_type == "endurance":
        return "200m echauffement varie\n3x300m nage reguliere R30s\n200m retour calme souple"
    if session_type == "endurance_sets":
        return "200m echauffement\n6x150m allure reguliere R20s\n4x50m propres sans forcer\n100m retour calme"
    if session_type == "recovery":
        return "200m nage souple\n8x50m faciles R15s\n100m retour calme"
    return "200m echauffement souple\n4x100m crawl technique R20s\n4x50m educatifs au choix R20s\n100m retour calme"


def _render_strength(session_type: str, *, duration_min: int) -> str:
    if session_type == "mobility":
        return "5min respiration + mobilite\n10min ouverture hanches/epaules\n10min controle et gainage doux"
    if session_type == "core":
        return "5min echauffement articulaire\n3x30s gainage ventral + 3x30s lateral\n3x10 dead bug + 3x12 bird dog\n5min retour calme"
    return "5min echauffement mobilite\n3x10 squats + 3x10 pompes + 3x10 rowing\n3x8 fentes par jambe + 3x30s gainage\n5min retour calme"


def _render_climbing(session_type: str, *, duration_min: int) -> str:
    if session_type == "bouldering":
        return "15min echauffement articulaire + voies faciles\n45min blocs projet (3-4 essais, repos complet)\n20min volume facile\n10min retour calme"
    return "15min echauffement articulaire + dalle facile\n50min grimpe technique / pieds / placements\n15min voies faciles retour calme"


# ---------------------------------------------------------------------------
# Parametric blueprint rendering
# ---------------------------------------------------------------------------


def render_blueprint(
    blueprint: SessionBlueprint,
    zones: AthleteZones,
    *,
    duration_min: int,
    athlete_level: str = "intermediate",
    cycle_week: int = 1,
) -> str:
    """Render a blueprint with real zone targets injected."""
    from fitmas.athlete_zones import get_zone_target

    lines: list[str] = []
    sport = blueprint.sport_type

    for block in blueprint.blocks:
        zone_band = get_zone_target(zones, sport, block.zone)
        zone_label = _format_zone_inline(zone_band, sport) if zone_band else block.zone

        if block.block_type == "intervals" and block.reps:
            reps = _resolve_reps(block, athlete_level=athlete_level, cycle_week=cycle_week)
            distance_part = f"x{block.rep_distance}" if block.rep_distance else f"x{block.rep_duration}" if block.rep_duration else ""
            rest_part = f" recup {_enrich_rest(block.rest_type, zones, sport)}" if block.rest_type else ""
            phase_label = _phase_prefix(block.phase)
            lines.append(f"{phase_label}{reps}{distance_part} @ {zone_label}{rest_part}")
        elif block.block_type == "progressive":
            dur = block.duration_min or 15
            lines.append(f"{dur}min echauffement progressif {zone_label}")
        elif block.block_type == "steady":
            if block.rep_distance:
                lines.append(f"{block.rep_distance} {block.phase} {zone_label}")
            else:
                dur = block.duration_min or 20
                phase_label = _phase_prefix(block.phase)
                lines.append(f"{phase_label}{dur}min {zone_label}")

    return "\n".join(lines)


def _resolve_reps(block: SessionBlock, *, athlete_level: str, cycle_week: int) -> int:
    if block.scaling is None:
        return block.reps or 6
    level_map = {
        "beginner": block.scaling.beginner_reps,
        "intermediate": block.scaling.intermediate_reps,
        "advanced": block.scaling.advanced_reps,
    }
    base_reps = level_map.get(athlete_level, block.scaling.intermediate_reps)
    # cycle_week 1 = baseline, 2 = +delta, 3 = +2*delta, 4 (recovery) = halved
    if cycle_week >= 4:
        return max(2, base_reps // 2)
    week_bonus = block.scaling.cycle_week_delta * max(0, cycle_week - 1)
    return base_reps + week_bonus


def _format_zone_inline(zone_band: object, sport: str) -> str:
    """Format a zone band as inline text like '4:20-4:30/km (Z5, FC ~175)'."""
    zone = getattr(zone_band, "zone", "")
    label = getattr(zone_band, "label", "")

    if sport in ("running", "trail"):
        pace_low = getattr(zone_band, "pace_low", None)
        pace_high = getattr(zone_band, "pace_high", None)
        hr_low = getattr(zone_band, "hr_low", None)
        hr_high = getattr(zone_band, "hr_high", None)
        if pace_low and pace_high:
            text = f"{pace_high} - {pace_low} ({zone})"
            if hr_low and hr_high:
                text += f" FC {hr_low}-{hr_high}"
            return text
    elif sport == "cycling":
        power_low = getattr(zone_band, "power_low", None)
        power_high = getattr(zone_band, "power_high", None)
        if power_low is not None and power_high is not None:
            return f"{power_low}-{power_high}W ({zone})"
    elif sport == "swimming":
        css_low = getattr(zone_band, "css_low", None)
        css_high = getattr(zone_band, "css_high", None)
        if css_low is not None and css_high is not None:
            return f"{css_low}-{css_high}s/100m ({zone})"

    return f"{zone} {label}"


def _enrich_rest(rest_type: str, zones: object, sport: str) -> str:
    """Enrich rest description with zone target if it references a zone."""
    from fitmas.athlete_zones import get_zone_target

    if "Z1" in rest_type:
        z1 = get_zone_target(zones, sport, "Z1")
        if z1:
            inline = _format_zone_inline(z1, sport)
            return rest_type.replace("Z1", inline.split("(")[0].strip())
    return rest_type


def _phase_prefix(phase: str) -> str:
    if phase == "warmup":
        return "Echauffement: "
    if phase == "cooldown":
        return "Retour calme: "
    return ""
