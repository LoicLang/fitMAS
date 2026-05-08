from fitmas import coach_voice
from fitmas.conversation_prompt_modules import (
    build_action_contract_system_text,
    build_calendar_truth_system_text,
    build_identity_voice_system_text,
    build_output_schema_system_text,
)


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
