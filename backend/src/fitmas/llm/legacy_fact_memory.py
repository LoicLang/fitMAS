from __future__ import annotations

import json
import re
from collections.abc import Callable

from fitmas.fact_memory import normalize_fact_payload as normalize_fact_memory_payload
from fitmas.fact_memory import select_relevant_facts
from fitmas.llm.legacy_onboarding import COACH_SOUL


def extract_facts(
    user_text: str,
    assistant_text: str,
    existing_facts: list[dict],
    *,
    request_json_fn: Callable[..., dict | None],
) -> list[dict]:
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

Pour chaque fait, evalue sa duree de vie selon la categorie:
- Une douleur/blessure/gene = category "health", persiste plusieurs semaines
- Une fatigue passagere = category "fatigue", dure 1-2 jours seulement
- Une indispo ponctuelle = category "availability", dure 1-3 jours
- Un objectif ou preference = category "goal"/"preference", persiste longtemps
- Un claim d'activite = category "execution", ne persiste que la journee
Ne confonds pas une blessure (long terme, affecte le plan) avec une fatigue (court terme, signal du jour).

IMPORTANT: Si un fait existant couvre deja le meme sujet (meme category + meme key ou sujet proche), utilise le MEME key avec action "upsert" pour le mettre a jour. Ne cree PAS de nouveau fait avec un key different pour le meme sujet.

Retourne un JSON: {{"facts": [...]}}

Chaque fact:
- category: "preference" | "constraint" | "pattern" | "coaching" | "fatigue" | "availability" | "health" | "goal" | "objective" | "execution"
- key: slug court (reutilise le key existant si c'est une mise a jour)
- value: phrase courte utile
- confidence: float 0..1
- confirmed: bool
- source: "conversation"
- action: "upsert" | "archive"

Si rien d'utile: {{"facts": []}}"""

    data = request_json_fn(system=COACH_SOUL, prompt=prompt, max_tokens=900)
    if data and isinstance(data.get("facts"), list):
        return [_normalize_fact_payload(fact) for fact in data["facts"] if isinstance(fact, dict)]
    return []


def select_prompt_facts(facts: list[dict]) -> list[str]:
    return select_relevant_facts([normalize_fact_memory_payload(fact) for fact in facts], affects=["conversation"], limit=6)


def _normalize_fact_payload(fact: dict) -> dict:
    value = str(fact.get("value", "")).strip()
    key = str(fact.get("key") or _slugify(value[:48])).strip() or "fact"
    category = str(fact.get("category", "preference")).strip() or "preference"
    action = str(fact.get("action", "upsert")).strip() or "upsert"
    normalized = {
        "category": category,
        "key": key,
        "value": value,
        "confidence": float(fact.get("confidence", 0.7)),
        "confirmed": bool(fact.get("confirmed", False)),
        "source": str(fact.get("source", "conversation")).strip() or "conversation",
        "action": action,
        "active": action != "archive",
    }
    return normalize_fact_memory_payload(normalized)


def _slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:120] or "fact"
