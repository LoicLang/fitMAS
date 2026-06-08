from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from fitmas.legacy.core import orm as s

logger = logging.getLogger(__name__)


def seed_if_empty(db: Session) -> None:
    """Seed a coherent multisport profile for Loïc if no user exists.

    This is a fallback so the webapp is usable even before Telegram onboarding.
    Real users go through /start on Telegram which calls the onboard endpoint.
    """
    existing = db.query(s.User).first()
    if existing is not None:
        return

    logger.info("No user found — seeding default multisport profile")

    user = s.User(
        name="Loïc",
        age=30,
        objective="Progresser en trail et escalade tout en gardant un socle vélo et natation",
        primary_objective="Progresser en trail et escalade tout en gardant un socle vélo et natation",
        weekly_structure_notes="Semaine chargée en journée. Créneaux le matin tôt ou en fin de journée. Week-end plus libre.",
        coaching_style="direct",
        coach_name="FitMAS",
        coach_style="Direct, pragmatique, pas de cheerleading. Tu parles comme un pote qui s'y connaît.",
        coach_relationship="Un binôme lucide. Tu me dis ce que je dois entendre, pas ce que je veux entendre.",
        coach_do="Donner des repères clairs. Adapter la charge au ressenti. Protéger la récupération.",
        coach_dont="Jamais de motivation creuse. Pas de emojis excessifs. Pas de formules toutes faites.",
        coach_soul="Tu es le coach que j'aurais voulu avoir plus tôt : quelqu'un qui comprend que la performance passe par la régularité et la lucidité, pas par la motivation du dimanche soir.",
        onboarding_status="completed",
    )
    db.add(user)
    db.flush()

    # Sports
    sports = [
        ("running", 0),
        ("climbing", 1),
        ("cycling", 2),
        ("swimming", 3),
        ("strength", 4),
    ]
    for sport_type, rank in sports:
        db.add(s.UserSport(user_id=user.id, sport_type=sport_type, priority_rank=rank, active=True))

    # Constraints
    constraints = [
        "Disponible surtout matin tôt et soir après 18h",
        "Week-end : créneaux longs possibles",
        "Pas de salle d'escalade le lundi (fermée)",
        "Vélo seulement outdoor quand la météo le permet",
    ]
    for text in constraints:
        db.add(s.UserConstraint(user_id=user.id, text=text))

    # Preferences
    preferences = [
        "Trail plutôt que route pour la course",
        "Escalade en bloc, pas de voie",
        "Natation en eau libre quand c'est possible",
        "Renfo fonctionnel, pas de musculation classique",
    ]
    for text in preferences:
        db.add(s.UserPreference(user_id=user.id, text=text))

    db.flush()

    # Weekly plan — realistic multisport
    plan = s.WeeklyPlan(
        user_id=user.id,
        intention="Construire une base solide trail + escalade avec un socle cardio vélo/natation",
        summary="Semaine équilibrée : 2 courses, 2 escalades, 1 vélo, 1 natation, 1 renfo. Charge progressive.",
        status="active",
    )
    db.add(plan)
    db.flush()

    days_data = [
        {
            "day": "monday",
            "label": "Lundi",
            "sport_type": "running",
            "session_type": "endurance",
            "session_title": "Footing vallonné",
            "session_goal": "Relancer en douceur après le week-end. Travail aérobie sur terrain varié.",
            "session_note": "Privilégie un parcours avec du dénivelé léger pour simuler le trail.",
            "duration_min": 50,
            "intensity": "easy",
            "load_score": 2,
            "priority": "Socle aérobie",
            "nutrition_focus": "Bien hydraté, petit-déjeuner léger avant si matin.",
            "flexibility": "flexible",
            "completion_status": "planned",
        },
        {
            "day": "tuesday",
            "label": "Mardi",
            "sport_type": "climbing",
            "session_type": "technique",
            "session_title": "Bloc technique",
            "session_goal": "Travailler la lecture de voie et la précision des pieds. Pas de force max.",
            "session_note": "Échauffement long. Blocs en dessous du niveau max pour polir la technique.",
            "duration_min": 75,
            "intensity": "moderate",
            "load_score": 2,
            "priority": "Technique grimpe",
            "nutrition_focus": "Collation protéinée après pour la récupération musculaire.",
            "flexibility": "stable",
            "completion_status": "planned",
        },
        {
            "day": "wednesday",
            "label": "Mercredi",
            "sport_type": "cycling",
            "session_type": "endurance",
            "session_title": "Sortie vélo endurance",
            "session_goal": "Volume aérobie sans forcer. Tourner les jambes, ventiler.",
            "session_note": "Idéal en extérieur. Si météo mauvaise, home trainer en zone 2.",
            "duration_min": 60,
            "intensity": "easy",
            "load_score": 2,
            "priority": "Socle cardio",
            "nutrition_focus": "Eau suffisante. Barre si sortie > 1h.",
            "flexibility": "flexible",
            "completion_status": "planned",
        },
        {
            "day": "thursday",
            "label": "Jeudi",
            "sport_type": "running",
            "session_type": "quality",
            "session_title": "Fractionné côtes",
            "session_goal": "Séance clé trail : 6×3min en côte, récup trot descente. Puissance aérobie.",
            "session_note": "Séance dure. Bien échauffé avant (15min footing). Écoute le corps.",
            "duration_min": 55,
            "intensity": "hard",
            "load_score": 3,
            "priority": "Séance clé",
            "nutrition_focus": "Bien manger la veille. Rien de lourd 2h avant.",
            "flexibility": "stable",
            "completion_status": "planned",
        },
        {
            "day": "friday",
            "label": "Vendredi",
            "sport_type": "swimming",
            "session_type": "technique",
            "session_title": "Natation technique",
            "session_goal": "Travail de glisse et respiration. Éducatifs + nage continue.",
            "session_note": "Objectif : fluidité, pas vitesse. Récupération active après la séance dure de jeudi.",
            "duration_min": 45,
            "intensity": "easy",
            "load_score": 1,
            "priority": "Récup active",
            "nutrition_focus": "Léger. La natation aide à récupérer.",
            "flexibility": "flexible",
            "completion_status": "planned",
        },
        {
            "day": "saturday",
            "label": "Samedi",
            "sport_type": "climbing",
            "session_type": "strength",
            "session_title": "Bloc force + renfo",
            "session_goal": "Blocs proches du niveau max. Enchaîner avec 20min de renfo fonctionnel.",
            "session_note": "Séance forte de la semaine en grimpe. Gainage, tractions, antagonistes après les blocs.",
            "duration_min": 90,
            "intensity": "hard",
            "load_score": 3,
            "priority": "Séance clé grimpe",
            "nutrition_focus": "Protéines et glucides après. Bien récupérer pour demain.",
            "flexibility": "stable",
            "completion_status": "planned",
        },
        {
            "day": "sunday",
            "label": "Dimanche",
            "sport_type": "running",
            "session_type": "long",
            "session_title": "Sortie longue trail",
            "session_goal": "Volume en terrain trail. 1h15–1h30 à allure confort, dénivelé libre.",
            "session_note": "Le cœur de la semaine trail. Pas de chrono, juste le plaisir du terrain.",
            "duration_min": 85,
            "intensity": "moderate",
            "load_score": 3,
            "priority": "Sortie longue",
            "nutrition_focus": "Petit-déjeuner consistant. Emporte de l'eau et un gel si > 1h15.",
            "flexibility": "stable",
            "completion_status": "planned",
        },
    ]

    for sort_order, d in enumerate(days_data):
        db.add(s.DayPlan(weekly_plan_id=plan.id, sort_order=sort_order, **d))

    # Initial coach message
    db.add(s.CoachMessage(
        user_id=user.id,
        role="agent",
        text="FitMAS est en place. Première semaine posée — trail, escalade, vélo, natation. On ajuste au fur et à mesure.",
    ))

    # Onboarding facts
    facts = [
        ("sport", "sport_principal", "Trail running", "onboarding", 1.0, True),
        ("sport", "sport_secondaire_1", "Escalade bloc", "onboarding", 1.0, True),
        ("sport", "sport_secondaire_2", "Vélo route/gravel", "onboarding", 0.9, True),
        ("sport", "sport_secondaire_3", "Natation eau libre", "onboarding", 0.8, True),
        ("constraint", "disponibilite", "Matin tôt ou soir après 18h en semaine", "onboarding", 1.0, True),
        ("constraint", "salle_escalade", "Salle fermée le lundi", "onboarding", 1.0, True),
        ("preference", "terrain", "Trail > route pour la course", "onboarding", 1.0, True),
        ("preference", "grimpe_style", "Bloc, pas de voie", "onboarding", 1.0, True),
        ("coaching", "coach_style_preference", "Direct, pragmatique, binôme lucide", "onboarding", 1.0, True),
    ]
    for cat, key, val, src, conf, confirmed in facts:
        db.add(s.UserFact(
            user_id=user.id,
            category=cat,
            key=key,
            value=val,
            source=src,
            confidence=conf,
            confirmed=confirmed,
            active=True,
        ))

    db.commit()
    logger.info("Seeded multisport profile for user %s (id=%s)", user.name, user.id)
