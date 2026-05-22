from fitmas.domain.coaching import coach_voice
from fitmas.conversation_prompting import select_conversation_prompt_policy
from fitmas.conversation_prompt_modules import (
    build_action_contract_system_text,
    build_calendar_truth_system_text,
    build_coach_voice_examples_system_text,
    build_conversation_system_text,
    build_identity_voice_system_text,
    build_output_schema_system_text,
    build_turn_scope_contract_system_text,
    build_tool_workflow_system_text,
)
from fitmas.prompt_contracts import get_prompt_contract
from fitmas.tools.routing import IntentCategory


def test_identity_voice_system_text_contains_voice_contract() -> None:
    text = build_identity_voice_system_text()

    assert text.startswith("Tu es FitMAS, un coach multisport IA.")
    assert "Posture coach (non-negociable):" in text
    assert coach_voice.COACH_VOICE_RULES in text
    assert "Workflow replan_after_constraint" not in text
    assert text.endswith("Telegram / app.")


def test_calendar_truth_system_text_contains_status_semantics() -> None:
    text = build_calendar_truth_system_text()

    assert text.startswith("Analyse le message utilisateur")
    assert "`adapted` = seance modifiee/remplacee/deplacee par FitMAS" in text
    assert "ce n'est PAS une preuve d'execution" in text
    assert "Pour dire qu'une seance a ete faite aujourd'hui" in text
    assert "Actions possibles:" not in text


def test_tool_workflow_system_text_contains_replan_workflow() -> None:
    text = build_tool_workflow_system_text()

    assert text.startswith("Workflow replan_after_constraint:")
    assert "suggest_replan_candidates" not in text
    assert "draft_move_session" not in text
    assert "validate_week_coherence" not in text
    assert "backend review sportive" in text
    assert "Actions possibles:" not in text
    assert "Analyse le message utilisateur" not in text


def test_coach_voice_examples_system_text_contains_good_and_bad_examples() -> None:
    text = build_coach_voice_examples_system_text()

    assert text == f"{coach_voice.COACH_VOICE_FEW_SHOTS_GOOD}\n\n{coach_voice.COACH_VOICE_FEW_SHOTS_BAD}"
    assert "Exemples BONS" in text
    assert "Exemples A NE JAMAIS ECRIRE" in text
    assert "Actions possibles:" not in text
    assert "Tu reponds UNIQUEMENT" not in text


def test_conversation_system_text_composes_modules_in_order() -> None:
    text = build_conversation_system_text()

    markers = [
        "Tu es FitMAS, un coach multisport IA.",
        "Workflow replan_after_constraint:",
        "Analyse le message utilisateur",
        "Actions possibles:",
        "Exemples BONS",
        "Tu reponds UNIQUEMENT avec un JSON CoachDecision valide.",
    ]
    positions = [text.index(marker) for marker in markers]

    assert positions == sorted(positions)
    assert text == "\n\n".join(
        (
            build_identity_voice_system_text(),
            build_tool_workflow_system_text(),
            build_calendar_truth_system_text(),
            build_action_contract_system_text(),
            build_coach_voice_examples_system_text(),
            build_output_schema_system_text(),
        )
    )


def test_conversation_system_text_can_include_turn_scope_contract() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    text = build_conversation_system_text(contract)

    markers = [
        "Tu es FitMAS, un coach multisport IA.",
        "Contrat du tour:",
        "Workflow replan_after_constraint compact:",
        "Analyse le message utilisateur",
        "Actions possibles compactes:",
        "Tu reponds UNIQUEMENT avec un JSON CoachDecision valide.",
    ]
    positions = [text.index(marker) for marker in markers]

    assert positions == sorted(positions)
    assert "- route: conversation_plan_negotiation" in text
    assert "- sortie decision: CoachDecision" in text
    assert "grounded_final_reply" not in text


def test_read_only_conversation_system_text_excludes_mutation_modules() -> None:
    contract = get_prompt_contract("conversation_plan_lookup")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "Verite read-only:" in text
    assert "Analyse le message utilisateur et decide quelle action prendre" not in text
    assert "Tu reponds UNIQUEMENT avec un JSON CoachDecision valide." in text
    assert "Exemples BONS" not in text
    assert "requires_confirmation avec contre-prop" not in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "draft_move_session" not in text
    assert "suggest_replan_candidates" not in text
    assert "Contrat de sortie read_only:" in text
    assert "response_type: reply | no_change" in text
    assert "plan_patch = {" not in text
    assert "memory_actions: liste optionnelle" not in text
    assert "record_execution_update" not in text


def test_read_only_conversation_system_text_uses_no_action_voice_pack() -> None:
    contract = get_prompt_contract("conversation_plan_lookup")

    text = build_conversation_system_text(contract)

    assert "Voix coach no-action:" in text
    assert "Si tu annonces un changement de plan" not in text
    assert "Si tu refuses ou demandes confirmation" not in text
    assert "Swap applique" not in text
    assert "Mutation enregistree" not in text
    assert "Exemples BONS" not in text
    assert "Le message est envoye TEL QUEL au user" in text
    assert "Longueur cible: 1 a 2 phrases" in text


def test_casual_chat_conversation_system_text_uses_no_action_coach_decision_schema() -> None:
    contract = get_prompt_contract("conversation_casual_chat")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "- route: conversation_casual_chat" in text
    assert "- sortie decision: CoachDecision" in text
    assert "Contrat de sortie terminal_text:" in text
    assert "response_type: reply | no_change" in text
    assert "Posture terminale:" in text
    assert "Analyse le message utilisateur" not in text
    assert "Etats du calendrier:" not in text
    assert "Exemples BONS" not in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "plan_patch = {" not in text
    assert "memory_actions: liste optionnelle" not in text
    assert "record_execution_update" not in text


def test_terminal_conversation_system_text_uses_no_action_voice_pack() -> None:
    contract = get_prompt_contract("conversation_close_turn")

    text = build_conversation_system_text(contract)

    assert "Voix coach no-action:" in text
    assert "Si tu annonces un changement de plan" not in text
    assert "Si tu refuses ou demandes confirmation" not in text
    assert "Swap applique" not in text
    assert "Mutation enregistree" not in text
    assert "Le message est envoye TEL QUEL au user" in text
    assert "Longueur cible: 1 a 2 phrases" in text


def test_close_turn_conversation_system_text_uses_no_action_coach_decision_schema() -> None:
    contract = get_prompt_contract("conversation_close_turn")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "- route: conversation_close_turn" in text
    assert "- sortie decision: CoachDecision" in text
    assert "Contrat de sortie terminal_text:" in text
    assert "response_type: reply | no_change" in text
    assert "pending_resolution: null sauf si un pending explicite est fourni" in text
    assert "Posture terminale:" in text
    assert "Analyse le message utilisateur" not in text
    assert "Etats du calendrier:" not in text
    assert "Exemples BONS" not in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "plan_patch = {" not in text
    assert "memory_actions: liste optionnelle" not in text
    assert "record_execution_update" not in text


def test_generic_question_system_text_stays_general_without_fact_promises() -> None:
    contract = get_prompt_contract("conversation_generic_question")

    text = build_conversation_system_text(contract)

    assert "Posture generic_question:" in text
    assert "pas a une opportunite de planning" in text
    assert "get_coach_lens" in text
    assert "contexte coach compact" in text
    assert "Ne recite pas la lentille" in text
    assert "aucun horizon date ou chiffre" in text
    assert "N'annonce pas de delai, de resultat ou de progression mesurable" in text
    assert "Contrat de sortie general_answer:" in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "plan_patch = {" not in text


def test_draft_action_conversation_system_text_excludes_candidate_tool_overlap() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "Workflow replan_after_constraint compact:" in text
    assert "Actions possibles compactes:" in text
    assert "suggest_replan_candidates" not in text
    assert "draft_move_session" not in text
    assert "draft_swap_sessions" not in text
    assert "draft_replace_session" not in text
    assert "draft_lighten_day" not in text
    assert "draft_create_session" not in text
    assert "candidate" not in text.lower()
    assert "validate_week_coherence" not in text
    assert "backend valide" in text
    assert "Contrat de sortie read_only:" not in text
    assert "PlanPatch:" in text


def test_draft_action_conversation_system_text_uses_compact_contract_modules() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    text = build_conversation_system_text(contract)

    assert "Posture draft_action:" in text
    assert "Workflow replan_after_constraint compact:" in text
    assert "Actions possibles compactes:" in text
    assert "Contrat de sortie draft_action:" in text
    assert "Exemples BONS" not in text
    assert "Exemples A NE JAMAIS ECRIRE" not in text
    assert "Few-shots actions structurees:" not in text
    assert "Few-shots capture indirecte:" not in text
    assert "Compat temporaire acceptee:" not in text


def test_execution_report_system_text_excludes_planning_mutation_modules() -> None:
    contract = get_prompt_contract("conversation_execution_report")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "- route: conversation_execution_report" in text
    assert "Contrat de sortie execution_report:" in text
    assert "record_execution_update" in text
    assert "record_health_signal" in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "suggest_replan_candidates" not in text
    assert "draft_move_session" not in text
    assert "plan_patch = {" not in text


def test_health_signal_system_text_keeps_bounded_planpatch_without_replan_manual() -> None:
    contract = get_prompt_contract("conversation_health_signal")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "- route: conversation_health_signal" in text
    assert "Contrat de sortie health_signal:" in text
    assert "record_health_signal" in text
    assert "signal_kind: pain | injury | fatigue | sleep | illness | tension | other" in text
    assert "PlanPatch minimal si adaptation evidente" in text
    assert "requires_confirmation exige un plan_patch valide" in text
    assert "Ne mets jamais un PlanPatch dans mutation_decision" in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "suggest_replan_candidates" not in text
    assert "draft_move_session" not in text
    assert "Few-shots actions structurees:" not in text


def test_availability_constraint_system_text_uses_dedicated_memory_first_contract() -> None:
    contract = get_prompt_contract("conversation_availability_constraint")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "- route: conversation_availability_constraint" in text
    assert "Contrat de sortie availability_constraint:" in text
    assert "record_availability" in text
    assert "plan_patch: null" in text
    assert "suggest_replan_candidates" not in text
    assert "draft_lighten_day" not in text
    assert "draft_replace_session" not in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "Few-shots actions structurees:" not in text


def test_health_signal_intent_uses_health_prompt_contract() -> None:
    policy = select_conversation_prompt_policy(intent=IntentCategory.HEALTH_SIGNAL)

    assert policy.name == "health_signal"
    assert policy.contract_name == "conversation_health_signal"


def test_legacy_conversation_system_text_keeps_full_module_set() -> None:
    text = build_conversation_system_text()

    assert "Contrat du tour:" not in text
    assert "Workflow replan_after_constraint:" in text
    assert "Actions possibles:" in text


def test_turn_scope_contract_system_text_renders_safe_contract_subset() -> None:
    contract = get_prompt_contract("conversation_plan_lookup")

    text = build_turn_scope_contract_system_text(contract)

    assert text.startswith("Contrat du tour:")
    assert "- route: conversation_plan_lookup" in text
    assert "- capacite: read_only" in text
    assert "- tools autorises: get_plan_window" in text
    assert "- actions autorisees: aucune" in text
    assert "- verites requises: temporal, plan_window" in text
    assert "- sortie decision: CoachDecision" in text
    assert "- parole finale: terminal_composer" in text
    assert "grounded_final_reply" not in text
    assert "output_schema" not in text


def test_action_contract_system_text_contains_actions_rules_and_examples() -> None:
    text = build_action_contract_system_text()

    assert text.startswith("Actions possibles:")
    assert '"move_session": move_session = deplacer une seule seance' in text
    assert "respecte cette hierarchie de verite:" in text
    assert "Exemples:" in text
    assert '"ok ca me va" -> no_change' in text
    assert "Exemples BONS (voix coach)" not in text
    assert "Tu reponds UNIQUEMENT" not in text


def test_output_schema_system_text_contains_json_contract() -> None:
    text = build_output_schema_system_text()

    assert text.startswith("Tu reponds UNIQUEMENT avec un JSON CoachDecision valide.")
    assert "memory_actions: liste optionnelle" in text
    assert "pending_resolution: optionnel" in text
    assert "plan_patch = {" in text
    assert "Compat temporaire acceptee:" in text
    assert text.endswith("Pas de markdown. Pas de texte autour du JSON.")
    assert "Exemples BONS (voix coach)" not in text
