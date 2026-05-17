from __future__ import annotations

import json
import logging
from typing import Any, Callable

from fitmas.llm.legacy_models import (
    AvailabilityConstraintAction,
    CoachDecision,
    ExecutionUpdateAction,
    HealthSignalAction,
    MemoryAction,
    PreferenceSignalAction,
)
from fitmas.llm.legacy_parser import (
    normalize_execution_actions,
    normalize_memory_actions,
    optional_int,
    parse_coach_decision_payload,
)

logger = logging.getLogger("fitmas.llm")

StructuredJSONRequest = Callable[..., dict | None]


def maybe_compile_execution_actions_for_turn(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
    request_structured_json_fn: StructuredJSONRequest,
) -> CoachDecision:
    if decision.execution_actions:
        return decision
    if not turn_has_execution_action_scope(coach_context):
        return decision
    compiler_payload = {
        "turn_plan": turn_plan_from_coach_context(coach_context),
        "execution_claim": execution_claim_from_coach_context(coach_context),
        "unresolved_execution_followup": (coach_context or {}).get("unresolved_execution_followup"),
        "unresolved_execution_followup_session_id": (coach_context or {}).get("unresolved_execution_followup_session_id"),
        "unresolved_execution_followup_target_date": (coach_context or {}).get("unresolved_execution_followup_target_date"),
        "decision": decision.model_dump(mode="json"),
    }
    compiler_prompt = (
        "EXECUTION_COMPILER\n"
        "Compile uniquement les actions d'execution FitMAS depuis les artefacts LLM et le contexte original.\n"
        "Le backend ne lit pas le texte utilisateur libre; toi, LLM, tu arbitres l'execution.\n\n"
        "Regles strictes:\n"
        "- sortie JSON unique: {\"execution_actions\": [...]}\n"
        "- PlanPatch interdit; mutation_decision interdite; memory_actions interdites; pending_resolution interdit\n"
        "- si la cible est claire, retourne record_execution_update\n"
        "- si la cible manque ou reste ambigue, retourne execution_actions=[]\n"
        "- ne change jamais la reponse coach, le plan_patch, ni les memory_actions existantes\n"
        "- action: type=record_execution_update, target_ref, target_session_id?, status=completed|not_completed|partially_completed|unknown, completed?, sport_type?, duration_min?, confidence, evidence?\n\n"
        "ARTEFACTS_MACHINE:\n"
        f"{json_for_compiler(compiler_payload)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n\n"
        "Retourne uniquement le JSON action-only."
    )
    data = request_action_compiler_json(
        system=system,
        prompt=compiler_prompt,
        max_tokens=700,
        compiler_name="execution",
        request_structured_json_fn=request_structured_json_fn,
    )
    actions = parse_execution_action_compiler_payload(data)
    if not actions:
        return decision
    logger.info("llm.execution_action_compiler actions=%s", len(actions))
    return decision.model_copy(update={"execution_actions": (*decision.execution_actions, *actions)})


def maybe_compile_memory_actions_for_turn(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
    request_structured_json_fn: StructuredJSONRequest,
) -> CoachDecision:
    compiled_actions: tuple[MemoryAction, ...] = ()
    if turn_has_health_memory_scope(coach_context) and not has_memory_action_type(decision, "record_health_signal"):
        compiled_actions = (
            *compiled_actions,
            *compile_memory_actions_for_scope(
                scope="health",
                compiler_label="HEALTH_MEMORY_COMPILER",
                allowed_action="record_health_signal",
                decision=decision,
                system=system,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=request_structured_json_fn,
            ),
        )
    if turn_has_availability_memory_scope(coach_context) and not has_memory_action_type(decision, "record_availability"):
        compiled_actions = (
            *compiled_actions,
            *compile_memory_actions_for_scope(
                scope="availability",
                compiler_label="AVAILABILITY_MEMORY_COMPILER",
                allowed_action="record_availability",
                decision=decision,
                system=system,
                prompt=prompt,
                coach_context=coach_context,
                request_structured_json_fn=request_structured_json_fn,
            ),
        )
    if not compiled_actions:
        return decision
    logger.info("llm.memory_action_compiler actions=%s", len(compiled_actions))
    return decision.model_copy(update={"memory_actions": (*decision.memory_actions, *compiled_actions)})


def compile_memory_actions_for_scope(
    *,
    scope: str,
    compiler_label: str,
    allowed_action: str,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
    request_structured_json_fn: StructuredJSONRequest,
) -> tuple[MemoryAction, ...]:
    scope_rule = (
        "- si le tour est health_signal et que le contexte original contient une douleur, blessure, fatigue, maladie ou resolution de signal sante, retourne record_health_signal meme si un plan_patch existe\n"
        if scope == "health"
        else (
            "- si le tour est availability_constraint et que le contexte original contient une indisponibilite, contrainte horaire, voyage ou limitation sport/date, retourne record_availability meme si un plan_patch existe\n"
            "- pour record_availability, aucune seance cible n'est necessaire; une fenetre datee/relative, une contrainte horaire ou une limitation de sport suffit\n"
            "- si le user distingue plusieurs statuts sur plusieurs dates (`aujourd'hui indispo mais demain dispo`), retourne plusieurs actions record_availability datees plutot qu'un seul `limited` large\n"
            "- si le user corrige une ancienne indisponibilite (`demain je suis dispo`), retourne une action `available` datee sur cette fenetre pour permettre au backend de resoudre l'ancienne contrainte\n"
            "- si la contrainte concerne un sport precis, renseigne sport_type avec le sport canonique si connu\n"
            "- si la cible planning reste ambigue ou demande clarification, record_availability reste requis quand la contrainte de disponibilite est claire\n"
            "- exemple: `non j'etais indispo aujourd'hui mais demain je suis dispo` -> deux actions: unavailable aujourd'hui, available demain\n"
            "- exemple: `Demain soir c'est impossible pour moi` -> record_availability window_text=\"demain soir impossible\", availability=unavailable\n"
            "- exemple: `Je ne peux pas nager deux semaines` -> record_availability window_text=\"natation impossible deux semaines\", availability=unavailable, sport_type=swimming\n"
        )
    )
    compiler_payload = {
        "action_expected_when_scope_confident": True,
        "allowed_action": allowed_action,
        "minimum_actions_when_scope_confident": 1,
        "scope": scope,
        "turn_intents": sorted(turn_intents_from_coach_context(coach_context)),
        "turn_plan": turn_plan_from_coach_context(coach_context),
        "selected_facts": (coach_context or {}).get("selected_facts"),
        "decision": decision.model_dump(mode="json"),
    }
    compiler_prompt = (
        f"{compiler_label}\n"
        "Compile uniquement les actions memoire FitMAS depuis les artefacts LLM et le contexte original.\n"
        "Le backend ne lit pas le texte utilisateur libre; toi, LLM, tu arbitres la memoire.\n\n"
        "Regles strictes:\n"
        "- sortie JSON unique: {\"memory_actions\": [...]}\n"
        f"- action autorisee: {allowed_action} seulement\n"
        "- PlanPatch interdit; mutation_decision interdite; execution_actions interdites; pending_resolution interdit\n"
        "- ARTEFACTS_MACHINE.action_expected_when_scope_confident=true: le turn planner a classe ce tour dans ce scope; retourne l'action autorisee sauf si le contexte original est explicitement hypothetique, meta, ou insuffisant\n"
        "- ARTEFACTS_MACHINE.minimum_actions_when_scope_confident=1: si le scope est confirme et que le message utilisateur porte bien ce signal, retourne au moins une action memoire autorisee\n"
        "- un plan_patch existant ne remplace jamais la memoire; la memoire doit etre compilee separement\n"
        f"{scope_rule}"
        "- memory_actions=[] est autorise uniquement si le contexte original est explicitement hypothetique, meta, tiers, ou trop ambigu pour creer une memoire coach\n"
        "- ne change jamais la reponse coach, le plan_patch, ni les execution_actions existantes\n\n"
        "Formes:\n"
        "- record_health_signal: health_signal, body_area?, signal_kind=pain|injury|fatigue|sleep|illness|tension|other, severity=mild|moderate|severe|unknown, status=new|ongoing|improving|worsening|resolved|unknown, confidence, evidence?\n"
        "- record_availability: window_text, availability=unavailable|limited|available|unknown, sport_type?, scope?, starts_on?, ends_on?, recurrence?, confidence, evidence?\n\n"
        "ARTEFACTS_MACHINE:\n"
        f"{json_for_compiler(compiler_payload)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n\n"
        "Retourne uniquement le JSON action-only."
    )
    data = request_action_compiler_json(
        system=system,
        prompt=compiler_prompt,
        max_tokens=700,
        compiler_name=scope,
        request_structured_json_fn=request_structured_json_fn,
    )
    actions = parse_memory_action_compiler_payload(data, allowed_action=allowed_action)
    if not actions and isinstance(data, dict):
        logger.info(
            "llm.memory_action_compiler_empty scope=%s keys=%s",
            scope,
            sorted(str(key) for key in data.keys()),
        )
    if not actions:
        strict_prompt = strict_memory_action_compiler_prompt(
            compiler_label=compiler_label,
            scope=scope,
            allowed_action=allowed_action,
            compiler_payload=compiler_payload,
            original_prompt=prompt,
        )
        strict_data = request_action_compiler_json(
            system=system,
            prompt=strict_prompt,
            max_tokens=500,
            compiler_name=f"{scope}_strict",
            request_structured_json_fn=request_structured_json_fn,
        )
        actions = parse_memory_action_compiler_payload(strict_data, allowed_action=allowed_action)
        if actions:
            logger.info("llm.memory_action_compiler_strict_retry scope=%s actions=%s", scope, len(actions))
    return actions


def strict_memory_action_compiler_prompt(
    *,
    compiler_label: str,
    scope: str,
    allowed_action: str,
    compiler_payload: dict[str, Any],
    original_prompt: str,
) -> str:
    if scope == "health":
        scope_rule = (
            "- si le message utilisateur porte une douleur, blessure, fatigue, maladie ou resolution de signal sante, retourne exactement un record_health_signal\n"
            "- un changement planning propose n'annule jamais la memoire sante\n"
        )
    else:
        scope_rule = (
            "- si le message utilisateur porte une indisponibilite, contrainte horaire, voyage ou limitation sport/date, retourne exactement un record_availability\n"
            "- aucune seance cible n'est necessaire pour record_availability\n"
            "- si le user distingue plusieurs statuts sur plusieurs dates (`aujourd'hui indispo mais demain dispo`), retourne plusieurs actions record_availability datees plutot qu'un seul `limited` large\n"
            "- si le user corrige une ancienne indisponibilite (`demain je suis dispo`), retourne une action `available` datee sur cette fenetre pour permettre au backend de resoudre l'ancienne contrainte\n"
            "- si la contrainte concerne un sport precis, renseigne sport_type avec le sport canonique si connu\n"
            "- si la cible planning est ambigue, record_availability reste requis quand la contrainte de disponibilite est claire\n"
        )
    return (
        f"STRICT_{compiler_label}\n"
        "Le premier compiler memoire a retourne une liste vide. Re-evalue uniquement la memoire.\n"
        "Le backend ne lit pas le texte utilisateur libre; toi, LLM, tu arbitres le signal.\n\n"
        "Regles strictes:\n"
        "- sortie JSON unique: {\"memory_actions\": [...]}\n"
        f"- action autorisee: {allowed_action} seulement\n"
        "- PlanPatch interdit; mutation_decision interdite; execution_actions interdites; pending_resolution interdit\n"
        "- retourne memory_actions=[] uniquement si le message est explicitement hypothetique, meta, tiers, ou trop ambigu pour creer une memoire coach\n"
        f"{scope_rule}\n"
        "ARTEFACTS_MACHINE:\n"
        f"{json_for_compiler(compiler_payload)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{original_prompt}\n\n"
        "Retourne uniquement le JSON action-only."
    )


def request_action_compiler_json(
    *,
    system: str,
    prompt: str,
    max_tokens: int,
    compiler_name: str,
    request_structured_json_fn: StructuredJSONRequest,
) -> dict | None:
    try:
        return request_structured_json_fn(
            system=(
                "Tu es un compiler FitMAS action-only. "
                "Tu ne produis jamais de message utilisateur, jamais de PlanPatch, jamais de tool call. "
                "Retourne uniquement un JSON valide avec la liste d'actions demandee."
            ),
            messages=[{"role": "user", "content": prompt}],
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.warning("llm.%s_action_compiler_failed error=%s", compiler_name, exc)
        return None


def parse_execution_action_compiler_payload(data: dict | None) -> tuple[ExecutionUpdateAction, ...]:
    if not isinstance(data, dict):
        return ()
    actions: list[ExecutionUpdateAction] = []
    for payload in normalize_execution_actions(data.get("execution_actions")):
        try:
            actions.append(ExecutionUpdateAction(**payload))
        except Exception:
            logger.warning("llm.execution_action_compiler_invalid_action")
    return tuple(actions)


def parse_memory_action_compiler_payload(
    data: dict | None,
    *,
    allowed_action: str,
) -> tuple[MemoryAction, ...]:
    if not isinstance(data, dict):
        return ()
    actions: list[MemoryAction] = []
    for payload in normalize_memory_actions(data.get("memory_actions")):
        if str(payload.get("type") or "") != allowed_action:
            continue
        try:
            if allowed_action == "record_health_signal":
                actions.append(HealthSignalAction(**payload))
            elif allowed_action == "record_availability":
                actions.append(AvailabilityConstraintAction(**payload))
            elif allowed_action == "record_preference":
                actions.append(PreferenceSignalAction(**payload))
        except Exception:
            logger.warning("llm.memory_action_compiler_invalid_action type=%s", allowed_action)
    return tuple(actions)


def turn_has_execution_action_scope(coach_context: dict | None) -> bool:
    if not coach_context:
        return False
    if coach_context.get("unresolved_execution_followup"):
        return True
    claim = execution_claim_from_coach_context(coach_context)
    if isinstance(claim, dict) and str(claim.get("status") or "").strip() in {"done", "not_done"}:
        return True
    intents = turn_intents_from_coach_context(coach_context)
    return bool(intents.intersection({"execution_report", "non_completion_claim", "activity_claim"}))


def turn_has_health_memory_scope(coach_context: dict | None) -> bool:
    return "health_signal" in turn_intents_from_coach_context(coach_context)


def turn_has_availability_memory_scope(coach_context: dict | None) -> bool:
    return "availability_constraint" in turn_intents_from_coach_context(coach_context)


def has_memory_action_type(decision: CoachDecision, action_type: str) -> bool:
    return any(str(getattr(action, "type", "") or "") == action_type for action in decision.memory_actions)


def turn_plan_from_coach_context(coach_context: dict | None) -> dict | None:
    raw = (coach_context or {}).get("turn_plan")
    return raw if isinstance(raw, dict) else None


def execution_claim_from_coach_context(coach_context: dict | None) -> dict | None:
    direct = (coach_context or {}).get("turn_execution_claim")
    if isinstance(direct, dict):
        return direct
    turn_plan = turn_plan_from_coach_context(coach_context)
    claim = (turn_plan or {}).get("execution_claim")
    return claim if isinstance(claim, dict) else None


def turn_intents_from_coach_context(coach_context: dict | None) -> set[str]:
    if not coach_context:
        return set()
    intents = {str(coach_context.get("turn_primary_intent") or "").strip()}
    intents.update(str(item).strip() for item in (coach_context.get("turn_secondary_intents") or ()))
    turn_plan = turn_plan_from_coach_context(coach_context)
    if turn_plan:
        intents.add(str(turn_plan.get("primary_intent") or "").strip())
        intents.update(str(item).strip() for item in (turn_plan.get("secondary_intents") or ()))
    return {intent for intent in intents if intent}


def json_for_compiler(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def maybe_repair_missing_execution_action_from_followup(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
    request_structured_json_fn: StructuredJSONRequest,
) -> CoachDecision:
    followup_session_id = optional_int((coach_context or {}).get("unresolved_execution_followup_session_id"))
    if decision.execution_actions:
        return decision
    normalized_decision_text = _normalize_for_execution_guard(" ".join([decision.fitmas_message, decision.rationale]))
    mentions_recent_execution = (
        followup_session_id is not None
        or "hier" in normalized_decision_text
        or "yesterday" in normalized_decision_text
        or looks_like_execution_update_artifact(normalized_decision_text)
    )
    if not mentions_recent_execution:
        return decision
    payload = decision.model_dump(mode="json")
    followup_text = str((coach_context or {}).get("unresolved_execution_followup") or "").strip()
    if followup_session_id is not None:
        target_instruction = (
            "Tu ne dois pas inventer de nouvelle seance: la seule cible autorisee est "
            f"target_session_id={followup_session_id}."
        )
    else:
        target_instruction = (
            "Si tu ajoutes une action sans id certain, utilise un target_ref naturel "
            "comme `seance d'hier`; le backend resoudra contre la DB."
        )
    repair_prompt = (
        "Verifie si cette CoachDecision a oublie `execution_actions` pour le suivi execution cible.\n"
        f"{target_instruction}\n"
        "Si le user repond que cette seance cible a ete faite, ajoute `record_execution_update` completed.\n"
        "Si le user repond que cette seance cible n'a pas ete faite, ajoute `record_execution_update` not_completed.\n"
        "Si le user ne repond pas au suivi execution, retourne exactement le meme JSON.\n"
        "Ne change pas les mutations planning ni les memory_actions deja valides.\n"
        "Retourne uniquement un JSON FitMAS CoachDecision valide.\n\n"
        f"SUIVI_EXECUTION_STRUCTURE:\n{followup_text or '(non fourni)'}\n\n"
        f"DECISION_A_VERIFIER:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n"
    )
    repaired = request_structured_json_fn(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    parsed = parse_coach_decision_payload(repaired)
    if parsed is None:
        logger.warning("llm.followup_execution_repair_invalid")
        return decision
    return parsed


def looks_like_execution_update_artifact(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    non_completion_terms = (
        "pas fait",
        "n a pas fait",
        "non realise",
        "non realisee",
        "manque",
        "manquee",
        "rate",
        "ratee",
        "saute",
        "skipped",
        "not completed",
    )
    execution_subjects = (
        "seance",
        "session",
        "renfo",
        "footing",
        "course",
        "running",
        "natation",
        "swim",
        "velo",
        "cycling",
    )
    return any(term in normalized_text for term in non_completion_terms) and any(
        subject in normalized_text for subject in execution_subjects
    )


def maybe_repair_execution_action_consistency(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
    request_structured_json_fn: StructuredJSONRequest,
) -> CoachDecision:
    if not bool((coach_context or {}).get("verify_execution_actions")):
        return decision
    if not decision.execution_actions:
        return decision
    payload = decision.model_dump(mode="json")
    repair_prompt = (
        "Verifie la coherence entre `fitmas_message` / `rationale` et `execution_actions`.\n"
        "Tu ne dois pas inventer de nouvelle seance ni changer une mutation planning.\n"
        "Si la phrase dit que la seance est faite mais que l'action dit not_completed, corrige l'action en completed.\n"
        "Si la phrase dit que la seance n'est pas faite mais que l'action dit completed, corrige l'action en not_completed.\n"
        "Si tout est coherent, retourne exactement le meme JSON.\n"
        "Retourne uniquement un JSON FitMAS CoachDecision valide.\n\n"
        f"DECISION_A_VERIFIER:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n"
    )
    repaired = request_structured_json_fn(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    parsed = parse_coach_decision_payload(repaired)
    if parsed is None:
        logger.warning("llm.execution_action_verifier_invalid")
        return decision
    return parsed


def maybe_repair_missing_availability_memory_action(
    *,
    decision: CoachDecision,
    system: str,
    prompt: str,
    coach_context: dict | None,
    request_structured_json_fn: StructuredJSONRequest,
) -> CoachDecision:
    if not bool((coach_context or {}).get("repair_memory_actions")):
        return decision
    if any(getattr(action, "type", "") == "record_availability" for action in decision.memory_actions):
        return decision
    intents = {
        str((coach_context or {}).get("turn_primary_intent") or "").strip(),
        *[str(item).strip() for item in ((coach_context or {}).get("turn_secondary_intents") or ())],
    }
    if "availability_constraint" not in intents:
        return decision
    payload = decision.model_dump(mode="json")
    repair_prompt = (
        "Verifie si cette CoachDecision oublie une `memory_actions.record_availability`.\n"
        "Tu es autorise a relire le contexte original comme LLM; le backend ne parse pas ce texte.\n"
        "Si le user exprime une contrainte durable ou datee de disponibilite, ajoute une action `record_availability`.\n"
        "Si le user distingue plusieurs statuts sur plusieurs dates (`aujourd'hui indispo mais demain dispo`), "
        "utilise plusieurs actions `record_availability` datees plutot qu'un seul `limited` large.\n"
        "Si le user corrige une ancienne indisponibilite (`demain je suis dispo`), ajoute une action "
        "`available` datee sur cette fenetre pour que le backend resolve l'ancienne contrainte.\n"
        "Si aucune contrainte de disponibilite n'est presente, retourne exactement le meme JSON.\n"
        "Ne change pas les mutations planning, pending_resolution ni execution_actions.\n"
        "Retourne uniquement un JSON FitMAS CoachDecision valide.\n\n"
        "FORME record_availability:\n"
        '{"type":"record_availability","window_text":"...","availability":"unavailable|limited|available|unknown",'
        '"sport_type":null,"scope":null,"starts_on":null,"ends_on":null,"confidence":0.75,"evidence":"..."}\n\n'
        f"DECISION_A_VERIFIER:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "CONTEXTE_ORIGINAL:\n"
        f"{prompt}\n"
    )
    repaired = request_structured_json_fn(
        system=system,
        messages=[{"role": "user", "content": repair_prompt}],
        max_tokens=1024,
    )
    parsed = parse_coach_decision_payload(repaired)
    if parsed is None:
        logger.warning("llm.availability_memory_repair_invalid")
        return decision
    return parsed


def _normalize_for_execution_guard(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()
