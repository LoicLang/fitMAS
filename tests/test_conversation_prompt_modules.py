from fitmas import coach_voice
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
    assert "suggest_replan_candidates" in text
    assert "draft_move_session" in text
    assert "validate_week_coherence" in text
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
        "Workflow replan_after_constraint:",
        "Analyse le message utilisateur",
        "Actions possibles:",
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
    assert "Analyse le message utilisateur" in text
    assert "Tu reponds UNIQUEMENT avec un JSON CoachDecision valide." in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "draft_move_session" not in text
    assert "suggest_replan_candidates" not in text
    assert "Contrat de sortie read_only:" in text
    assert "response_type: reply | no_change" in text
    assert "plan_patch = {" not in text
    assert "memory_actions: liste optionnelle" not in text
    assert "record_execution_update" not in text


def test_casual_chat_conversation_system_text_uses_no_action_coach_decision_schema() -> None:
    contract = get_prompt_contract("conversation_casual_chat")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "- route: conversation_casual_chat" in text
    assert "- sortie decision: CoachDecision" in text
    assert "Contrat de sortie terminal_text:" in text
    assert "response_type: reply | no_change" in text
    assert "Workflow replan_after_constraint:" not in text
    assert "Actions possibles:" not in text
    assert "plan_patch = {" not in text
    assert "memory_actions: liste optionnelle" not in text
    assert "record_execution_update" not in text


def test_draft_action_conversation_system_text_keeps_mutation_modules() -> None:
    contract = get_prompt_contract("conversation_plan_negotiation")

    text = build_conversation_system_text(contract)

    assert "Contrat du tour:" in text
    assert "Workflow replan_after_constraint:" in text
    assert "Actions possibles:" in text
    assert "draft_move_session" in text
    assert "suggest_replan_candidates" in text
    assert "Contrat de sortie read_only:" not in text
    assert "plan_patch = {" in text


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
    assert "- tools autorises: get_plan_window, get_session_detail" in text
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
