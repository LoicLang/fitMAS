from __future__ import annotations

from sqlalchemy.orm import Session

from fitmas import schema as s


def seed_if_empty(db: Session) -> None:
    """Populate DB with V0 seed data if empty. No-op if user already exists."""
    if db.query(s.User).count() > 0:
        return

    user = s.User(
        name="Loic",
        age=31,
        objective="Progresser sur 10 km / semi sans rendre la semaine trop rigide.",
        coaching_style="Direct, calme, pas cheerleader.",
    )
    db.add(user)
    db.flush()

    for text in [
        "Mardi soir fragile",
        "Jeudi prefere leger",
        "Sortie longue plutot dimanche matin",
    ]:
        db.add(s.UserConstraint(user_id=user.id, text=text))

    for text in [
        "Aime les produits tech",
        "Veut comprendre ce qui change sans grands discours",
        "Veut moins gerer seul la planification",
    ]:
        db.add(s.UserPreference(user_id=user.id, text=text))

    plan = s.WeeklyPlan(
        user_id=user.id,
        intention="Placer un vrai bloc de qualite sans rigidifier la semaine.",
        summary="Mardi reste flexible, jeudi porte le bloc fort, et dimanche reste le repere long.",
        status="active",
    )
    db.add(plan)
    db.flush()

    days = [
        dict(
            sort_order=0, day="monday", label="Lundi",
            session_title="Sortie facile 45 min",
            session_goal="Lancer la semaine proprement",
            session_note="Pas besoin de bruit aujourd'hui. L'app suffit.",
            priority="Clarte", flexibility="stable",
            nutrition_focus="Pense surtout a bien remettre quelque chose apres la seance.",
            change_notes=[("Rien n'a bouge", "Le meilleur choix aujourd'hui, c'est de garder la semaine simple.")],
            watch_items=[("Recuperation generale", "On lit surtout comment le corps repond au depart de semaine.")],
        ),
        dict(
            sort_order=1, day="tuesday", label="Mardi",
            session_title="Creneau fragile",
            session_goal="Verifier si le bon jour reste mardi ou bascule jeudi",
            session_note="On ne force pas un creneau instable.",
            priority="Clarification", flexibility="flexible",
            nutrition_focus="Rien a pousser tant que le bon creneau n'est pas confirme.",
            change_notes=[("Bloc qualite en attente", "FitMAS verifie si jeudi devient le meilleur point d'ancrage.")],
            watch_items=[
                ("Agenda du soir", "Mardi ne doit pas casser tout le bloc de la semaine."),
                ("Qualite", "Le bon jour compte plus que tenir un plan rigide."),
            ],
        ),
        dict(
            sort_order=2, day="wednesday", label="Mercredi",
            session_title="Footing simple ou repos mobile",
            session_goal="Garder de l'air pour proteger la qualite",
            session_note="La semaine reste propre pendant qu'on protege le bloc fort.",
            priority="Stabilite", flexibility="flexible",
            nutrition_focus="Routine simple, sans surjouer.",
            change_notes=[("Mercredi reste simple", "Le deplacement de la qualite evite de raidir le milieu de semaine.")],
            watch_items=[("Souplesse agenda", "On garde de la marge pour jeudi.")],
        ),
        dict(
            sort_order=3, day="thursday", label="Jeudi",
            session_title="Bloc qualite",
            session_goal="Valider la vraie seance cle de la semaine",
            session_note="Mieux place ici que force mardi.",
            priority="Seance cle", flexibility="stable",
            nutrition_focus="Prevois quelque chose avant si le creneau est serre, puis une recup simple derriere.",
            change_notes=[
                ("Seance deplacee ici", "Mardi ne paraissait pas assez stable cette semaine."),
                ("Vendredi sera plus light", "Si le bloc passe bien, la recup du lendemain sera protegee."),
            ],
            watch_items=[
                ("Qualite de seance", "Le but est de valider le bloc proprement, pas d'aller trop loin."),
                ("Recup demain", "Le lendemain dira comment ajuster la suite."),
            ],
        ),
        dict(
            sort_order=4, day="friday", label="Vendredi",
            session_title="Journee plus light",
            session_goal="Encaisser le bloc d'hier",
            session_note="Aujourd'hui on consolide, on n'empile pas.",
            priority="Recuperation", flexibility="stable",
            nutrition_focus="Ne sous-mange pas aujourd'hui. L'objectif est de consolider.",
            change_notes=[("Vendredi allege", "Le bloc d'hier etait solide, on protege la suite.")],
            watch_items=[
                ("Jambes", "FitMAS veut savoir si la fatigue est normale ou plus lourde."),
                ("Dimanche", "La sortie longue depend aussi de ce qui se passe aujourd'hui."),
            ],
        ),
        dict(
            sort_order=5, day="saturday", label="Samedi",
            session_title="Preparation legere",
            session_goal="Arriver propre sur la sortie longue",
            session_note="Rien a compliquer aujourd'hui.",
            priority="Preparation", flexibility="stable",
            nutrition_focus="Reste simple et laisse de la place a demain.",
            change_notes=[("Pas de bruit", "Si rien ne coince, FitMAS laisse de l'espace.")],
            watch_items=[("Fraicheur", "Le long de dimanche reste le vrai repere de fin de semaine.")],
        ),
        dict(
            sort_order=6, day="sunday", label="Dimanche",
            session_title="Sortie longue",
            session_goal="Fermer la semaine avec un vrai repere",
            session_note="C'est ici qu'on lit si la structure tenait.",
            priority="Repere fort", flexibility="stable",
            nutrition_focus="Avant la sortie: simple et digeste. Apres: recup propre.",
            change_notes=[("Semaine coherente", "Le deplacement de mardi n'a pas casse la logique globale.")],
            watch_items=[
                ("Tenue du bloc", "FitMAS lit si l'ensemble reste soutenable dans la vraie vie."),
                ("Semaine prochaine", "Le message de preparation part seulement si ca vaut le coup."),
            ],
        ),
    ]

    for d in days:
        change_notes = d.pop("change_notes")
        watch_items = d.pop("watch_items")
        day_row = s.DayPlan(weekly_plan_id=plan.id, **d)
        db.add(day_row)
        db.flush()
        for title, detail in change_notes:
            db.add(s.ChangeNote(day_plan_id=day_row.id, title=title, detail=detail))
        for title, detail in watch_items:
            db.add(s.WatchItem(day_plan_id=day_row.id, title=title, detail=detail))

    # Seed initial messages
    for role, text in [
        ("agent", "Je suis en train d'ajuster ta semaine. Tu peux courir demain matin ou c'est mort et on bascule plutot a jeudi ?"),
        ("user", "Mardi ca sent pas bon, plutot jeudi."),
        ("agent", "Ca marche. Je garde mercredi simple et je pose la qualite jeudi pour que le bloc reste propre."),
        ("agent", "Belle seance aujourd'hui. Le bloc est bien passe. Je garde demain un peu plus light pour bien encaisser."),
    ]:
        db.add(s.CoachMessage(user_id=user.id, role=role, text=text))

    db.commit()
