from __future__ import annotations

from fitmas.models import ChangeNote, DayId, DayPlan, Message, MessageRole, Profile, WatchItem, WeeklyPlan


def build_profile() -> Profile:
    return Profile(
        name="Loic",
        age=31,
        objective="Progresser sur 10 km / semi sans rendre la semaine trop rigide.",
        coaching_style="Direct, calme, pas cheerleader.",
        constraints=[
            "Mardi soir fragile",
            "Jeudi prefere leger",
            "Sortie longue plutot dimanche matin",
        ],
        preferences=[
            "Aime les produits tech",
            "Veut comprendre ce qui change sans grands discours",
            "Veut moins gerer seul la planification",
        ],
        integrations=["Sign in with Apple", "Apple Health", "Strava", "WhatsApp"],
    )


def build_week_plan() -> WeeklyPlan:
    return WeeklyPlan(
        intention="Placer un vrai bloc de qualite sans rigidifier la semaine.",
        summary="Mardi reste flexible, jeudi porte le bloc fort, et dimanche reste le repere long.",
        days=[
            DayPlan(
                day=DayId.MONDAY,
                label="Lundi",
                session_title="Sortie facile 45 min",
                session_goal="Lancer la semaine proprement",
                session_note="Pas besoin de bruit aujourd'hui. L'app suffit.",
                priority="Clarte",
                nutrition_focus="Pense surtout a bien remettre quelque chose apres la seance.",
                change_notes=[ChangeNote(title="Rien n'a bouge", detail="Le meilleur choix aujourd'hui, c'est de garder la semaine simple.")],
                watch_items=[WatchItem(title="Recuperation generale", detail="On lit surtout comment le corps repond au depart de semaine.")],
                flexibility="stable",
            ),
            DayPlan(
                day=DayId.TUESDAY,
                label="Mardi",
                session_title="Creneau fragile",
                session_goal="Verifier si le bon jour reste mardi ou bascule jeudi",
                session_note="On ne force pas un creneau instable.",
                priority="Clarification",
                nutrition_focus="Rien a pousser tant que le bon creneau n'est pas confirme.",
                change_notes=[
                    ChangeNote(title="Bloc qualite en attente", detail="FitMAS verifie si jeudi devient le meilleur point d'ancrage."),
                ],
                watch_items=[
                    WatchItem(title="Agenda du soir", detail="Mardi ne doit pas casser tout le bloc de la semaine."),
                    WatchItem(title="Qualite", detail="Le bon jour compte plus que tenir un plan rigide."),
                ],
                flexibility="flexible",
            ),
            DayPlan(
                day=DayId.WEDNESDAY,
                label="Mercredi",
                session_title="Footing simple ou repos mobile",
                session_goal="Garder de l'air pour proteger la qualite",
                session_note="La semaine reste propre pendant qu'on protege le bloc fort.",
                priority="Stabilite",
                nutrition_focus="Routine simple, sans surjouer.",
                change_notes=[ChangeNote(title="Mercredi reste simple", detail="Le deplacement de la qualite evite de raidir le milieu de semaine.")],
                watch_items=[WatchItem(title="Souplesse agenda", detail="On garde de la marge pour jeudi.")],
                flexibility="flexible",
            ),
            DayPlan(
                day=DayId.THURSDAY,
                label="Jeudi",
                session_title="Bloc qualite",
                session_goal="Valider la vraie seance cle de la semaine",
                session_note="Mieux place ici que force mardi.",
                priority="Seance cle",
                nutrition_focus="Prevois quelque chose avant si le creneau est serre, puis une recup simple derriere.",
                change_notes=[
                    ChangeNote(title="Seance deplacee ici", detail="Mardi ne paraissait pas assez stable cette semaine."),
                    ChangeNote(title="Vendredi sera plus light", detail="Si le bloc passe bien, la recup du lendemain sera protegee."),
                ],
                watch_items=[
                    WatchItem(title="Qualite de seance", detail="Le but est de valider le bloc proprement, pas d'aller trop loin."),
                    WatchItem(title="Recup demain", detail="Le lendemain dira comment ajuster la suite."),
                ],
                flexibility="stable",
            ),
            DayPlan(
                day=DayId.FRIDAY,
                label="Vendredi",
                session_title="Journee plus light",
                session_goal="Encaisser le bloc d'hier",
                session_note="Aujourd'hui on consolide, on n'empile pas.",
                priority="Recuperation",
                nutrition_focus="Ne sous-mange pas aujourd'hui. L'objectif est de consolider.",
                change_notes=[ChangeNote(title="Vendredi allege", detail="Le bloc d'hier etait solide, on protege la suite.")],
                watch_items=[
                    WatchItem(title="Jambes", detail="FitMAS veut savoir si la fatigue est normale ou plus lourde."),
                    WatchItem(title="Dimanche", detail="La sortie longue depend aussi de ce qui se passe aujourd'hui."),
                ],
                flexibility="stable",
            ),
            DayPlan(
                day=DayId.SATURDAY,
                label="Samedi",
                session_title="Preparation legere",
                session_goal="Arriver propre sur la sortie longue",
                session_note="Rien a compliquer aujourd'hui.",
                priority="Preparation",
                nutrition_focus="Reste simple et laisse de la place a demain.",
                change_notes=[ChangeNote(title="Pas de bruit", detail="Si rien ne coince, FitMAS laisse de l'espace.")],
                watch_items=[WatchItem(title="Fraicheur", detail="Le long de dimanche reste le vrai repere de fin de semaine.")],
                flexibility="stable",
            ),
            DayPlan(
                day=DayId.SUNDAY,
                label="Dimanche",
                session_title="Sortie longue",
                session_goal="Fermer la semaine avec un vrai repere",
                session_note="C'est ici qu'on lit si la structure tenait.",
                priority="Repere fort",
                nutrition_focus="Avant la sortie: simple et digeste. Apres: recup propre.",
                change_notes=[ChangeNote(title="Semaine coherente", detail="Le deplacement de mardi n'a pas casse la logique globale.")],
                watch_items=[
                    WatchItem(title="Tenue du bloc", detail="FitMAS lit si l'ensemble reste soutenable dans la vraie vie."),
                    WatchItem(title="Semaine prochaine", detail="Le message de preparation part seulement si ca vaut le coup."),
                ],
                flexibility="stable",
            ),
        ],
    )


def build_messages() -> list[Message]:
    return [
        Message(
            role=MessageRole.AGENT,
            text="Je suis en train d'ajuster ta semaine. Tu peux courir demain matin ou c'est mort et on bascule plutot a jeudi ?",
        ),
        Message(role=MessageRole.USER, text="Mardi ca sent pas bon, plutot jeudi."),
        Message(
            role=MessageRole.AGENT,
            text="Ca marche. Je garde mercredi simple et je pose la qualite jeudi pour que le bloc reste propre.",
        ),
        Message(
            role=MessageRole.AGENT,
            text="Belle seance aujourd'hui. Le bloc est bien passe. Je garde demain un peu plus light pour bien encaisser.",
        ),
    ]
