from fitmas.strength_engine import build_strength_workout


def test_strength_engine_protects_legs_when_run_support_is_detected() -> None:
    workout = build_strength_workout(
        session={
            "sport_type": "strength",
            "session_type": "general",
            "session_goal": "Stabiliser le tronc.",
            "session_note": "Jambes lourdes, on protege la course de demain.",
            "duration_min": 32,
            "intensity": "easy",
        }
    )

    assert workout.blueprint_key == "upper_core_protect_legs"
    assert not any("Squat" in step or "Fente" in step for step in workout.execution)
    assert any("Pompes" in step or "Wall slides" in step for step in workout.execution)


def test_strength_engine_protects_shoulders_when_swim_support_is_detected() -> None:
    workout = build_strength_workout(
        session={
            "sport_type": "strength",
            "session_type": "general",
            "session_goal": "Renfo utile avant la piscine.",
            "session_note": "Epaule sensible, on soutient la natation sans overhead.",
            "duration_min": 36,
            "intensity": "easy",
        }
    )

    assert workout.blueprint_key == "lower_stability_protect_shoulders"
    assert not any("Pompes" in step for step in workout.execution)
    assert any("Pont fessier" in step or "Squat" in step for step in workout.execution)
