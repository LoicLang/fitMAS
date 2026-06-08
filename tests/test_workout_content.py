from fitmas.legacy.domain.planning.workout_content import build_workout_content


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
    assert any("pont fessier" in step.lower() or "wall slides" in step.lower() for step in content.execution)


def test_strength_content_normalizes_composite_sport_and_ignores_stale_swim_description() -> None:
    content = build_workout_content(
        {
            "sport_type": "strength/general",
            "session_type": "training",
            "session_goal": "Poser les fondations musculaires.",
            "session_note": "Natation impossible, on remplace par renfo.",
            "session_description": "200m echauffement nage libre\n4x100m crawl technique",
            "duration_min": 34,
        }
    )

    assert content.objective == "Poser les fondations musculaires."
    assert content.rationale == "Natation impossible, on remplace par renfo."
    assert len(content.execution) >= 3
    assert not any("crawl" in step.lower() or "nage" in step.lower() for step in content.execution)


def test_strength_content_uses_recent_signals_for_compressed_prescription() -> None:
    content = build_workout_content(
        {
            "id": 30,
            "sport_type": "strength",
            "session_type": "general",
            "session_goal": "Faire juste utile.",
            "session_note": "On coupe sans bricoler.",
            "session_description": "",
            "scheduled_date": "2026-03-31T07:00:00+02:00",
            "duration_min": 25,
            "intensity": "easy",
        },
        recent_reality={
            "planned_sessions_7d": 4,
            "compliance_confirmed": 0.25,
            "planned_tss_7d": 120.0,
            "load_ratio": 0.45,
            "missed_streak_days": 3,
        },
        active_facts=(
            {"category": "fatigue", "key": "fatigue_today", "value": "fatigue residuelle aujourd'hui"},
        ),
        surrounding_sessions=(
            {
                "id": 31,
                "sport_type": "running",
                "scheduled_date": "2026-04-01T07:00:00+02:00",
                "priority": "High",
                "load_score": 3,
            },
        ),
    )

    assert len(content.execution) <= 4
    assert not any("squat" in step.lower() or "fente" in step.lower() for step in content.execution)
