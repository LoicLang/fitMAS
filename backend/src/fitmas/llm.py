from __future__ import annotations

import json
import logging
import os
import re

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SOUL = """\
Tu es FitMAS, un coach multisport IA.
Ton ton: clair, court, precis, confiant, chaleureux sans faux enthousiasme.
Tu parles comme un coach exigeant et calme, jamais comme un bot.
Tu reponds toujours en francais.
Tu ne dis jamais "Bravo continue comme ca" ou autre compliment generique.
Chaque message est contextuel et ancre dans un signal reel.
Tu tutoies toujours l'utilisateur.\
"""

_COACH_SOUL = """\
Tu incarnes le coach personnel de FitMAS.
Tu ecris en francais.
Tu es humain, lucide, calme, precis.
Tu ne sonnes jamais comme un template, jamais comme une pub, jamais comme un bot.
Tu aides a construire une relation de coaching credible des la premiere interaction.\
"""


class MutationDecision(BaseModel):
    mutation_type: str        # "move_session" | "lighten_day" | "swap_sessions" | "update_session" | "no_change"
    from_day: str | None = None
    to_day: str | None = None
    new_title: str | None = None
    new_goal: str | None = None
    rationale: str            # 1 phrase, pour les change notes
    fitmas_message: str       # message envoye a l'utilisateur


_DAYS_FR_TO_EN = {
    "lundi": "monday", "mardi": "tuesday", "mercredi": "wednesday",
    "jeudi": "thursday", "vendredi": "friday", "samedi": "saturday",
    "dimanche": "sunday",
}


def _normalize_day(raw: str | None) -> str | None:
    """Convert French day names to English keys, pass through English names."""
    if not raw:
        return None
    key = raw.strip().lower()
    return _DAYS_FR_TO_EN.get(key, key)


def _client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return None


def _request_text(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 512) -> str | None:
    client = _client()
    if not client:
        return None
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        logger.exception("LLM text call failed")
        return None


def _request_json(*, system: str, prompt: str, model: str = "claude-haiku-4-5-20251001", max_tokens: int = 1024) -> dict | None:
    raw = _request_text(system=system, prompt=prompt, model=model, max_tokens=max_tokens)
    if not raw:
        return None
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to decode LLM JSON: %s", raw[:200])
        return None


def decide(
    user_text: str,
    plan_summary: str,
    conversation_history: list[dict] | None = None,
    coach_context: dict | None = None,
    remembered_facts: list[dict] | None = None,
) -> MutationDecision | None:
    """
    Call the LLM to extract intent and decide a plan mutation.
    Returns None if LLM is unavailable (API key missing or error) -- caller falls back to rules.
    """
    if not _client():
        logger.info("No Anthropic client available — falling back to rules")
        return None

    # Build conversation context
    history_block = ""
    if conversation_history:
        recent = conversation_history[-8:]  # last 8 messages for context
        lines = []
        for msg in recent:
            prefix = "Utilisateur" if msg["role"] == "user" else "FitMAS"
            lines.append(f"{prefix}: {msg['text']}")
        history_block = f"\nHistorique recent:\n" + "\n".join(lines) + "\n"

    coach_block = ""
    if coach_context:
        coach_block = (
            "\nContexte coach:\n"
            f"- nom: {coach_context.get('coach_name', 'FitMAS')}\n"
            f"- style: {coach_context.get('coach_style', 'direct')}\n"
            f"- relation: {coach_context.get('coach_relationship', '')}\n"
            f"- fait bien: {coach_context.get('coach_do', '')}\n"
            f"- ne fait jamais: {coach_context.get('coach_dont', '')}\n"
            f"- ame: {coach_context.get('coach_soul', '')}\n"
        )

    facts_block = ""
    selected_facts = (coach_context or {}).get("selected_facts") or select_prompt_facts(remembered_facts or [])
    if selected_facts:
        facts_block = "\nMemoire utile:\n" + "\n".join(f"- {fact}" for fact in selected_facts) + "\n"

    prompt = f"""Plan de la semaine:
{plan_summary}
{coach_block}{facts_block}
{history_block}
Nouveau message de l'utilisateur:
{user_text}

Analyse ce message et decide quelle action prendre sur le plan de la semaine.

Actions possibles:
- "move_session": deplacer une seance d'un jour a un autre (from_day + to_day)
- "swap_sessions": echanger les seances de deux jours (from_day + to_day)
- "lighten_day": alleger un jour (from_day seul)
- "update_session": modifier le titre ou l'objectif d'un jour (from_day + new_title et/ou new_goal)
- "no_change": aucune modification necessaire

Les jours doivent etre en anglais: monday, tuesday, wednesday, thursday, friday, saturday, sunday.

Exemples:
- "mardi c'est mort, je bascule sur jeudi" → move_session, from_day: "tuesday", to_day: "thursday"
- "mercredi j'ai une grosse journee" → lighten_day, from_day: "wednesday"
- "echange samedi et dimanche" → swap_sessions, from_day: "saturday", to_day: "sunday"
- "jeudi je prefere faire du fractionne" → update_session, from_day: "thursday", new_title: "Fractionne 8x400m"
- "ok ca me va" → no_change

Reponds avec un JSON valide contenant exactement ces champs:
- "mutation_type": une des valeurs ci-dessus
- "from_day": jour source (anglais) ou null
- "to_day": jour destination (anglais) ou null
- "new_title": nouveau titre de seance si update_session, null sinon
- "new_goal": nouvel objectif si update_session, null sinon
- "rationale": explication courte (1 phrase, pour les notes de changement)
- "fitmas_message": message a envoyer a l'utilisateur — court, direct, ancre dans le contexte

Reponds UNIQUEMENT avec le JSON, sans markdown, sans texte autour."""

    try:
        data = _request_json(system=_SOUL, prompt=prompt)
        if not data:
            return None

        # Normalize French day names to English
        data["from_day"] = _normalize_day(data.get("from_day"))
        data["to_day"] = _normalize_day(data.get("to_day"))

        decision = MutationDecision(**data)
        logger.info(
            "LLM decision: %s (from=%s, to=%s) — %s",
            decision.mutation_type, decision.from_day, decision.to_day,
            decision.rationale,
        )
        return decision

    except Exception:
        logger.exception("LLM call failed — falling back to rules")
        return None


def make_plan_summary(days: list) -> str:
    """Build a compact plan summary to inject into the LLM prompt."""
    lines = []
    for d in days:
        lines.append(
            f"- {d.label} ({d.day}): [{getattr(d, 'sport_type', 'running')}] {d.session_title} — {d.session_goal} "
            f"(priorite: {d.priority}, flexibilite: {d.flexibility})"
        )
    return "\n".join(lines)


def preview_coach_voice(context: dict) -> list[str]:
    prompt = f"""Contexte user:
- objectif: {context['primary_objective']}
- sports: {", ".join(context['sports'])}
- style: {context['coach_style']}
- relation voulue: {context['coach_relationship']}
- ce que le coach doit faire: {context['coach_do']}
- ce qu'il ne doit jamais faire: {context['coach_dont']}
- ame libre: {context['coach_soul']}

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

    data = _request_json(system=_COACH_SOUL, prompt=prompt, max_tokens=700)
    if data and isinstance(data.get("messages"), list) and len(data["messages"]) >= 3:
        return [str(message).strip() for message in data["messages"][:3]]

    return _fallback_voice_preview(context)


def formulate_onboarding_recap(context: dict) -> str:
    prompt = f"""Tu dois rediger le recap final d'un onboarding.

Contexte:
- sports: {", ".join(context['sports'])}
- objectif: {context['primary_objective']}
- realite de semaine: {context['weekly_structure_notes']}
- contraintes: {" ; ".join(context['constraints']) or "aucune precisee"}
- preferences: {" ; ".join(context['preferences']) or "aucune precisee"}
- coach: {context['coach_name']} / style {context['coach_style']}
- ame: {context['coach_soul']}

Ecris un recap court en 4 a 6 lignes:
- ce que FitMAS a compris
- les arbitrages les plus probables
- le ton du coach

Pas de markdown complexe. Pas de phrase creuse."""

    text = _request_text(system=_COACH_SOUL, prompt=prompt, max_tokens=320)
    if text:
        return text
    return _fallback_recap(context)


def formulate_week_plan(planner_output: dict, user_profile: dict, coach_profile: dict) -> dict:
    prompt = f"""Tu dois enrichir un squelette de semaine multisport sans changer sa structure.

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

Squelette:
{json.dumps(planner_output, ensure_ascii=False)}

Retourne un JSON avec:
- intention
- summary
- days: liste de 7 objets dans le meme ordre

Chaque day doit contenir uniquement:
- day
- session_note
- watch_title
- watch_detail

Regles:
- ne change jamais sport_type, session_type, duration_min, intensity, load_score, priority, flexibility
- ancre la voix dans le coach
- pas de phrases generiques
- chaque note doit aider a comprendre la place de la seance dans la semaine"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, model="claude-sonnet-4-20250514", max_tokens=1500)
    if data:
        try:
            return _merge_week_enrichment(planner_output, data)
        except Exception:
            logger.exception("Failed to merge enriched week plan")
    return _fallback_week_plan(planner_output, coach_profile)


def _merge_week_enrichment(planner_output: dict, enrichment: dict) -> dict:
    base_days = planner_output["days"]
    enriched_days = enrichment.get("days", [])
    by_day = {day["day"]: day for day in enriched_days if isinstance(day, dict) and day.get("day")}

    merged_days = []
    for day in base_days:
        payload = by_day.get(day["day"], {})
        watch_title = payload.get("watch_title")
        watch_detail = payload.get("watch_detail")
        merged_days.append(
            {
                **day,
                "session_note": str(payload.get("session_note") or day["session_note"]).strip(),
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
    coach_name = context["coach_name"]
    return [
        f"{coach_name} est la. Mardi a l'air fragile. Je prefere garder de l'air plutot que forcer un faux bloc.",
        f"Je te construis une semaine tenable. Si mardi bouge, je garde la structure et je deplace intelligemment.",
        f"Je veux une semaine qui te ressemble, pas une semaine parfaite sur le papier. On pose les bons reperes et on garde du jeu.",
    ]


def _fallback_recap(context: dict) -> str:
    sports = ", ".join(context["sports"])
    constraints = ", ".join(context["constraints"][:3]) or "pas de contrainte forte explicite"
    return (
        f"Voila ce que j'ai retenu pour commencer.\n"
        f"Tu veux avancer sur {context['primary_objective']} avec une semaine ou {sports} doivent cohabiter proprement.\n"
        f"Je garde en tete: {constraints}.\n"
        f"Le coach va parler en mode {context['coach_style']}, avec une voix plus humaine que robotique, et il evitera {context['coach_dont'] or 'les phrases vides'}."
    )


def _fallback_week_plan(planner_output: dict, coach_profile: dict) -> dict:
    days = []
    for day in planner_output["days"]:
        days.append(
            {
                **day,
                "session_note": _fallback_day_note(day, coach_profile),
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


def extract_facts(user_text: str, assistant_text: str, existing_facts: list[dict]) -> list[dict]:
    prompt = f"""Analyse cet echange et decide s'il faut memoriser des faits utiles pour le coach.

Faits deja connus:
{json.dumps(existing_facts, ensure_ascii=False)}

Utilisateur:
{user_text}

Coach:
{assistant_text}

Tu dois extraire seulement des faits:
- stables
- personnels
- actionnables
- utiles pour les prochaines decisions

Ne memorise PAS:
- humeur passagere
- phrase vague
- details jetables
- diagnostics

Retourne un JSON: {{"facts": [...]}}

Chaque fact:
- category: "preference" | "constraint" | "pattern" | "coaching" | "fatigue"
- key: slug court
- value: phrase courte utile
- confidence: float 0..1
- confirmed: bool
- source: "conversation"
- action: "upsert" | "archive"

Si rien d'utile: {{"facts": []}}"""

    data = _request_json(system=_COACH_SOUL, prompt=prompt, max_tokens=900)
    if data and isinstance(data.get("facts"), list):
        return [_normalize_fact_payload(fact) for fact in data["facts"] if isinstance(fact, dict)]
    return _fallback_extract_facts(user_text)


def select_prompt_facts(facts: list[dict]) -> list[str]:
    if not facts:
        return []

    category_priority = {
        "constraint": 0,
        "pattern": 1,
        "preference": 2,
        "coaching": 3,
        "fatigue": 4,
    }
    active = [fact for fact in facts if fact.get("active", True)]
    active.sort(
        key=lambda fact: (
            0 if fact.get("confirmed") else 1,
            category_priority.get(fact.get("category", ""), 9),
            -float(fact.get("confidence", 0.0)),
        )
    )

    selected: list[str] = []
    seen = set()
    for fact in active:
        key = (fact.get("category"), fact.get("key"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(f"[{fact.get('category')}] {fact.get('value')}")
        if len(selected) >= 6:
            break
    return selected


def _fallback_extract_facts(user_text: str) -> list[dict]:
    text = user_text.strip()
    lowered = text.lower()
    facts: list[dict] = []

    if any(token in lowered for token in ("prefere", "préfère", "j'aime", "j aime")):
        facts.append(
            {
                "category": "preference",
                "key": _slugify(text[:48]),
                "value": text,
                "confidence": 0.72,
                "confirmed": True,
                "source": "conversation",
                "action": "upsert",
            }
        )

    if any(day in lowered for day in ("mardi", "jeudi", "lundi", "mercredi", "vendredi", "samedi", "dimanche")) and any(
        token in lowered for token in ("fragile", "pas dispo", "indispo", "jamais", "souvent", "complique", "compliqué")
    ):
        facts.append(
            {
                "category": "constraint",
                "key": _slugify(text[:48]),
                "value": text,
                "confidence": 0.76,
                "confirmed": True,
                "source": "conversation",
                "action": "upsert",
            }
        )

    if "escalade" in lowered and any(token in lowered for token in ("lourd", "lourde", "fatigue", "crame", "cramé")):
        facts.append(
            {
                "category": "pattern",
                "key": "escalade_charge_lendemain",
                "value": text,
                "confidence": 0.7,
                "confirmed": True,
                "source": "conversation",
                "action": "upsert",
            }
        )

    return [_normalize_fact_payload(fact) for fact in facts]


def _normalize_fact_payload(fact: dict) -> dict:
    value = str(fact.get("value", "")).strip()
    key = str(fact.get("key") or _slugify(value[:48])).strip() or "fact"
    category = str(fact.get("category", "preference")).strip() or "preference"
    action = str(fact.get("action", "upsert")).strip() or "upsert"
    return {
        "category": category,
        "key": key,
        "value": value,
        "confidence": float(fact.get("confidence", 0.7)),
        "confirmed": bool(fact.get("confirmed", False)),
        "source": str(fact.get("source", "conversation")).strip() or "conversation",
        "action": action,
        "active": action != "archive",
    }


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:120] or "fact"
