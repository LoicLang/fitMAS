from fitmas.workout_content import build_workout_content


def test_workout_content_filters_system_like_rationale_and_nutrition() -> None:
    content = build_workout_content(
        {
            "sport_type": "swimming",
            "session_type": "technique",
            "session_goal": "Retrouver les appuis.",
            "session_note": "ClawCoach garde cette seance lisible et utile.",
            "session_description": "200m echauffement\n4x100m technique R20s\n100m retour calme",
            "nutrition_focus": "Rester simple. Le but est surtout de soutenir la regularite.",
        }
    )

    assert content.objective == "Retrouver les appuis."
    assert content.rationale == "Retrouver les appuis."
    assert content.execution == (
        "200m echauffement",
        "4x100m technique R20s",
        "100m retour calme",
    )
    assert content.nutrition_note == "Hydrate-toi bien et reste sur quelque chose de simple aujourd'hui."


def test_strength_content_falls_back_to_actionable_execution() -> None:
    content = build_workout_content(
        {
            "sport_type": "strength",
            "session_type": "general",
            "session_goal": "Stabiliser le corps.",
            "session_note": "Support léger pour la semaine.",
            "session_description": "",
            "duration_min": 36,
        }
    )

    assert content.rationale == "Support léger pour la semaine."
    assert len(content.execution) >= 3
    assert any("squats" in step.lower() for step in content.execution)
