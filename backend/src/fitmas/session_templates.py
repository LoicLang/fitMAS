from __future__ import annotations

from dataclasses import dataclass


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


_TEMPLATES: tuple[SessionTemplate, ...] = (
    SessionTemplate("running", "easy", "Footing endurance", "Faire du volume souple sans bruit.", "Regulier", "Le vrai sujet est de finir frais.", 45, "easy", 1),
    SessionTemplate("running", "long", "Sortie longue course", "Construire une base d'endurance stable.", "Energie", "Ne pars pas trop vite. Garde du jus jusqu'au bout.", 75, "moderate", 3),
    SessionTemplate("running", "tempo", "Tempo course", "Travailler le seuil sans casser la semaine.", "Allure", "Reste propre. Pas de sprint inutile.", 55, "hard", 3),
    SessionTemplate("running", "intervals", "Fractionne court", "Stimuler la vitesse utile avec recup complete.", "Recuperation", "Le lendemain dira si la dose etait juste.", 55, "hard", 3),
    SessionTemplate("running", "fartlek", "Fartlek progressif", "Remettre du rythme avec moins de rigidite.", "Ressenti", "Ajuste si les jambes sont lourdes.", 50, "moderate", 2),
    SessionTemplate("running", "recovery", "Footing recup", "Faire circuler sans ajouter de dette.", "Souplesse", "Tu dois finir plus frais qu'au depart.", 30, "easy", 1),
    SessionTemplate("cycling", "endurance", "Sortie velo endurance", "Poser du volume propre et regulier.", "Cadence", "Reste fluide et stable.", 90, "moderate", 2),
    SessionTemplate("cycling", "sweet_spot", "Sweet spot velo", "Monter la puissance durable sans exploser.", "Gestion", "Ne transforme pas ca en VO2.", 75, "hard", 3),
    SessionTemplate("cycling", "intervals", "Intervalles velo", "Travailler les changements de rythme utiles.", "Recuperation", "Respecte les recups, sinon coupe une rep.", 70, "hard", 3),
    SessionTemplate("cycling", "recovery", "Velo recup", "Tourner les jambes et faire redescendre la charge.", "Souplesse", "Mouline, ne pousse pas.", 45, "easy", 1),
    SessionTemplate("swimming", "technique", "Natation technique", "Retrouver appuis et qualite de nage.", "Amplitude", "Reste long dans l'eau.", 40, "easy", 1),
    SessionTemplate("swimming", "endurance", "Natation endurance", "Construire un volume nage propre.", "Glisse", "Ne force pas la frequence.", 55, "moderate", 2),
    SessionTemplate("swimming", "endurance_sets", "Natation serie endurance", "Tenir des blocs reguliers sans se crisper.", "Regulier", "Garde le meme geste du debut a la fin.", 50, "moderate", 2),
    SessionTemplate("swimming", "css", "Natation qualite", "Stimuler la vitesse utile dans l'eau.", "Technique sous fatigue", "Si le geste se casse, reduis la serie.", 45, "hard", 3),
    SessionTemplate("swimming", "recovery", "Natation souple", "Bouger et delier sans charger.", "Souplesse", "Respiration calme, geste propre.", 30, "easy", 1),
    SessionTemplate("strength", "general", "Renfo general", "Stabiliser le corps sans prendre toute la place.", "Proprete", "Mieux vaut propre que lourd.", 40, "moderate", 2),
    SessionTemplate("strength", "core", "Core et stabilite", "Renforcer la tenue et les appuis.", "Controle", "Pas de rep sale en fin de serie.", 30, "easy", 1),
    SessionTemplate("strength", "mobility", "Mobilite active", "Rendre les articulations plus disponibles.", "Respiration", "Laisse de la place, ne force pas.", 25, "easy", 1),
    SessionTemplate("climbing", "technique", "Escalade technique", "Prendre de la grimpe utile sans trop de dette.", "Pieds", "Qualite des placements avant tout.", 90, "moderate", 2),
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


def render_session_description(template: SessionTemplate, *, duration_min: int | None = None) -> str:
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
