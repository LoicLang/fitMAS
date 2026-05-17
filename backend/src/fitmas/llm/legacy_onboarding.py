from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from fitmas.knowledge import load_sport_knowledge
from fitmas.onboarding_contract import build_coach_profile, build_goal_summary
from fitmas.time_context import build_time_context, render_time_context

logger = logging.getLogger("fitmas.llm")

COACH_SOUL = """\
Tu incarnes le coach personnel de FitMAS.
Tu ecris en francais.
Tu es humain, lucide, calme, precis.
Tu ne sonnes jamais comme un template, jamais comme une pub, jamais comme un bot.
Tu aides a construire une relation de coaching credible des la premiere interaction.\
"""


def preview_coach_voice(
    context: dict,
    *,
    time_context: dict | None = None,
    request_json_fn: Callable[..., dict | None],
) -> list[str]:
    resolved_time_context = time_context or build_time_context(context.get("timezone"))
    coach = build_coach_profile(context)
    prompt = f"""{render_time_context(resolved_time_context)}
Contexte user:
- cap: {build_goal_summary(context)}
- sports: {", ".join(context['sports'])}
- realite de semaine: {context.get('weekly_structure_notes', '')}
- etat actuel: {context.get('current_state_notes', '') or 'encore en cours de calibration'}
- preset: {coach['coach_preset_label']}
- style: {coach['coach_style']}
- relation voulue: {coach['coach_relationship']}
- ce que le coach doit faire: {coach['coach_do']}
- ce qu'il ne doit jamais faire: {coach['coach_dont']}
- ame libre: {coach['coach_soul']}

Genere exactement 3 messages courts que ce coach pourrait envoyer.
Scenario:
- la semaine vient d'etre comprise
- mardi parait fragile
- il faut montrer de la presence sans surjouer

Contraintes:
- 1 ou 2 phrases max par message
- chaque proposition doit avoir une saveur differente mais rester dans la meme ame
- pas de compliment generique
- reponds en JSON: {{"messages": ["...", "...", "..."]}}"""

    data = request_json_fn(system=COACH_SOUL, prompt=prompt, max_tokens=700)
    if data and isinstance(data.get("messages"), list) and len(data["messages"]) >= 3:
        return [str(message).strip() for message in data["messages"][:3]]

    return _fallback_voice_preview(context)


def formulate_onboarding_recap(
    context: dict,
    *,
    time_context: dict | None = None,
    request_text_fn: Callable[..., str | None],
) -> str:
    resolved_time_context = time_context or build_time_context(context.get("timezone"))
    coach = build_coach_profile(context)
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois rediger le recap final d'un onboarding.

Contexte:
- sports: {", ".join(context['sports'])}
- cap: {build_goal_summary(context)}
- realite de semaine: {context['weekly_structure_notes']}
- etat actuel: {context.get('current_state_notes', '') or 'encore a lire sur les premieres semaines'}
- contraintes: {" ; ".join(context['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(context['preferences']) or "aucune precisee"}
- coach: {coach['coach_name']} / preset {coach['coach_preset_label']} / style {coach['coach_style']}
- ame: {coach['coach_soul']}

Ecris un recap court en 4 a 6 lignes:
- ce que FitMAS a compris
- ce que tu protegeras des le debut
- ce qui reste encore a clarifier si besoin
- le ton du coach

Pas de markdown complexe. Pas de phrase creuse."""

    text = request_text_fn(system=COACH_SOUL, prompt=prompt, max_tokens=320)
    if text:
        return text
    return _fallback_recap(context)


def formulate_week_plan(
    planner_output: dict,
    user_profile: dict,
    coach_profile: dict,
    *,
    time_context: dict | None = None,
    request_json_fn: Callable[..., dict | None],
) -> dict:
    resolved_time_context = time_context or build_time_context(user_profile.get("timezone") or coach_profile.get("timezone"))
    sports_set = set(user_profile.get("sports", []))
    knowledge_block = load_sport_knowledge(sports_set, max_tokens=1500)
    planning_context = planner_output.get("planning_context") or {}
    planning_context_block = ""
    if planning_context:
        planning_context_block = (
            "\nDecision de planning deja prise hors LLM:\n"
            f"- planning_mode: {planning_context.get('planning_mode')}\n"
            f"- weekly_target_tss: {planning_context.get('weekly_target_tss')}\n"
            f"- key_session_count: {planning_context.get('key_session_count')}\n"
            f"- strength_session_count: {planning_context.get('strength_session_count')}\n"
            f"- long_session: {planning_context.get('long_session')}\n"
            f"- rationale: {' ; '.join(planning_context.get('rationale') or [])}\n"
            f"- adaptations: {' ; '.join(planning_context.get('adaptations') or [])}\n"
        )
    prompt = f"""{render_time_context(resolved_time_context)}
Tu dois enrichir un squelette de semaine multisport pour que chaque seance soit directement utilisable en situation reelle.

User:
- objectif: {user_profile['primary_objective']}
- sports: {", ".join(user_profile['sports'])}
- realite de semaine: {user_profile['weekly_structure_notes']}
- contraintes: {" ; ".join(user_profile['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(user_profile['preferences']) or "aucune precisee"}

Coach:
- nom: {coach_profile['coach_name']}
- style: {coach_profile['coach_style']}
- relation: {coach_profile['coach_relationship']}
- fait: {coach_profile['coach_do']}
- ne fait jamais: {coach_profile['coach_dont']}
- ame: {coach_profile['coach_soul']}
{planning_context_block}

Connaissances sport (utilise comme reference pour formuler les seances):
{knowledge_block}

Squelette:
{json.dumps(planner_output, ensure_ascii=False)}

Retourne un JSON avec:
- intention
- summary
- days: liste de 7 objets dans le meme ordre

Chaque day doit contenir:
- day
- session_title: titre court et precis (ex: "Footing endurance 45min zone 2", "Fractionne 8x400m R1min", "Natation technique 4x200m")
- session_goal: objectif clair en 1 phrase actionnable
- session_description: le deroulement complet de la seance, structure en blocs. C'est le champ le plus important.
- session_note: note de contexte sur la place de la seance dans la semaine (1-2 phrases)
- watch_title
- watch_detail

REGLE CRITIQUE — session_description:
Chaque session_description doit etre un plan de seance concret que l'utilisateur peut suivre tel quel.
Format: blocs separes par des retours a la ligne, avec durees/distances/intensites.

Exemples par sport:
- Running easy: "Echauffement 10min marche/trot\\n30min footing zone 2 (allure confortable, on peut parler)\\n5min retour au calme marche"
- Running quality: "Echauffement 15min footing progressif\\n8x400m a allure 10k, recup 1min trot\\n10min retour au calme footing lent"
- Running long: "10min trot lent\\n55min footing endurance zone 2 (regulier, pas d'acceleration)\\n5min marche retour calme\\nObjectif: finir frais, pas vide"
- Natation technique: "200m echauffement nage libre souple\\n4x100m crawl technique (rattrapé, poings fermés, amplitude) R20s\\n4x50m sprint 80% R30s\\n200m retour calme dos/brasse"
- Natation easy: "200m echauffement varié (crawl/dos)\\n8x50m crawl allure reguliere R15s\\n4x25m au choix\\n100m souple retour calme"
- Velo endurance: "15min echauffement progressif\\n50min zone 2 cadence 85-95rpm\\n10min retour calme moulinette"
- Escalade bloc: "15min echauffement articulaire + dalle facile\\n45min blocs projet (3-4 essais par bloc, repos complet entre)\\n20min volume facile\\n10min etirements"
- Renfo/strength: "Echauffement 5min mobilite\\n3x12 squats + 3x10 pompes + 3x30s gainage\\n2x15 fentes + 2x10 rowing\\nEtirements 5min"
- Repos: pas de session_description (laisser vide)

Adapte les distances, allures et series au niveau de l'utilisateur et a la duree prevue dans le squelette.
Ne mets JAMAIS de description vague comme "Fais ta seance normalement" ou "Seance de natation classique".

Regles:
- ne change jamais sport_type, session_type, duration_min, intensity, load_score, priority, flexibility
- ancre la voix dans le coach
- pas de phrases generiques
- session_title doit etre plus precis que le squelette (ajouter volume, allure, format)
- session_goal doit dire ce que la seance construit concretement
- session_description est le coeur: plan de seance structuré, blocs clairs, actionnable immediatement"""

    data = request_json_fn(system=COACH_SOUL, prompt=prompt, model="claude-sonnet-4-6", max_tokens=3000)
    if data:
        try:
            return _merge_week_enrichment(planner_output, data)
        except Exception:
            logger.exception("Failed to merge enriched week plan")
    return _fallback_week_plan(planner_output, coach_profile)


def _sanitize_coach_text(text: str, fallback: str) -> str:
    """Reject LLM output that looks like a leaked prompt or instruction."""
    if not text:
        return fallback
    leak_markers = (
        "l'utilisateur",
        "the user",
        "genere ",
        "génère ",
        "transforme ",
        "reponds en json",
        "réponds en json",
        "session_note",
        "session_title",
    )
    lower = text.lower()
    if any(marker in lower for marker in leak_markers):
        logger.warning("Prompt leak detected in LLM output, using fallback: %s", text[:80])
        return fallback
    return text


def _merge_week_enrichment(planner_output: dict, enrichment: dict) -> dict:
    base_days = planner_output["days"]
    enriched_days = enrichment.get("days", [])
    by_day = {day["day"]: day for day in enriched_days if isinstance(day, dict) and day.get("day")}

    merged_days = []
    for day in base_days:
        payload = by_day.get(day["day"], {})
        watch_title = payload.get("watch_title")
        watch_detail = payload.get("watch_detail")
        enriched_title = str(payload.get("session_title") or "").strip()
        enriched_goal = str(payload.get("session_goal") or "").strip()
        enriched_description = str(payload.get("session_description") or "").strip()
        raw_note = str(payload.get("session_note") or day["session_note"]).strip()
        merged_days.append(
            {
                **day,
                "session_title": enriched_title if enriched_title else day["session_title"],
                "session_goal": enriched_goal if enriched_goal else day["session_goal"],
                "session_note": _sanitize_coach_text(raw_note, day["session_note"]),
                "session_description": _sanitize_coach_text(enriched_description, day.get("session_description", "")) if enriched_description else day.get("session_description", ""),
                "watch_items": [
                    (
                        str(watch_title).strip() if watch_title else day["watch_items"][0][0],
                        str(watch_detail).strip() if watch_detail else day["watch_items"][0][1],
                    )
                ],
            }
        )

    return {
        "intention": str(enrichment.get("intention") or planner_output["intention_seed"]).strip(),
        "summary": str(enrichment.get("summary") or planner_output["intention_seed"]).strip(),
        "days": merged_days,
    }


def _fallback_voice_preview(context: dict) -> list[str]:
    coach = build_coach_profile(context)
    coach_name = coach["coach_name"]
    return [
        f"{coach_name} est la. Mardi a l'air fragile. Je prefere garder de l'air plutot que forcer un faux bloc.",
        f"Je te construis une semaine tenable. Si mardi bouge, je garde la structure et je deplace intelligemment.",
        f"Je veux une semaine qui te ressemble, pas une semaine parfaite sur le papier. On pose les bons reperes et on garde du jeu.",
    ]


def _fallback_recap(context: dict) -> str:
    coach = build_coach_profile(context)
    sports = ", ".join(context["sports"])
    constraints = ", ".join(context["constraints"][:3]) or "pas de contrainte forte explicite"
    goal_summary = build_goal_summary(context) or context["primary_objective"]
    current_state = context.get("current_state_notes") or "forme recente encore a affiner"
    return (
        f"Voila ce que j'ai retenu pour commencer.\n"
        f"Tu veux avancer sur {goal_summary} avec une semaine ou {sports} doivent cohabiter proprement.\n"
        f"Etat de depart retenu: {current_state}.\n"
        f"Je garde en tete: {constraints}.\n"
        f"Je protegerai d'abord les creneaux tenables et les seances qui comptent vraiment.\n"
        f"Le coach va parler en mode {coach['coach_preset_label'].lower()}, avec une voix {coach['coach_soul']}, et il evitera {coach['coach_dont'] or 'les phrases vides'}."
    )


def _fallback_week_plan(planner_output: dict, coach_profile: dict) -> dict:
    days = []
    for day in planner_output["days"]:
        days.append(
            {
                **day,
                "session_note": _fallback_day_note(day, coach_profile),
                "session_description": day.get("session_description", ""),
                "watch_items": day["watch_items"],
            }
        )

    return {
        "intention": planner_output["intention_seed"],
        "summary": _fallback_summary(days, coach_profile["coach_name"]),
        "days": days,
    }


def _fallback_day_note(day: dict, coach_profile: dict) -> str:
    coach_name = coach_profile["coach_name"]
    if day["sport_type"] == "rest":
        return f"{coach_name} laisse de l'air ici. Mieux vaut garder de la marge que remplir pour rien."
    if day["priority"] == "Seance cle":
        return f"{coach_name} pose ce bloc ici parce qu'il doit compter sans casser le reste."
    if day["priority"] == "Repere fort":
        return f"{coach_name} garde ce repere pour lire si la semaine tient vraiment dans la vraie vie."
    return f"{coach_name} garde cette seance lisible et utile. Le but est d'empiler proprement, pas de rajouter du bruit."


def _fallback_summary(days: list[dict], coach_name: str) -> str:
    active = [day for day in days if day["sport_type"] != "rest"]
    sports = ", ".join(sorted({day["sport_type"] for day in active}))
    return f"{coach_name} pose une semaine claire entre {sports}, avec un bloc fort, un repere long, et assez d'air pour que ca reste vivable."
