from fitmas.strength_signals import derive_strength_signals


def test_strength_signals_detect_low_week_fatigue_and_short_time() -> None:
    signals = derive_strength_signals(
        session={
            "id": 10,
            "sport_type": "strength",
            "scheduled_date": "2026-03-31T07:00:00+02:00",
            "duration_min": 25,
            "session_note": "On garde quelque chose de propre.",
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
        nearby_sessions=(
            {
                "id": 11,
                "sport_type": "running",
                "scheduled_date": "2026-04-01T07:00:00+02:00",
                "priority": "High",
                "load_score": 3,
            },
        ),
    )

    assert signals.recent_completion_band == "low"
    assert signals.recent_load_band == "low"
    assert signals.fatigue_flag is True
    assert signals.available_time_band == "short"
    assert signals.protected_sport == "running"


def test_strength_signals_use_health_flags_and_swim_protection() -> None:
    signals = derive_strength_signals(
        session={
            "id": 20,
            "sport_type": "strength",
            "scheduled_date": "2026-03-31T07:00:00+02:00",
            "duration_min": 35,
            "session_note": "Support propre.",
        },
        active_facts=(
            {
                "category": "health",
                "key": "reported_health_shoulder_swimming",
                "value": "gene a l'epaule quand il fait swimming",
            },
        ),
        nearby_sessions=(
            {
                "id": 21,
                "sport_type": "swimming",
                "scheduled_date": "2026-04-01T07:00:00+02:00",
                "priority": "High",
                "load_score": 2,
            },
        ),
    )

    assert "shoulder_pain" in signals.health_flags
    assert signals.protected_sport == "swimming"
    assert signals.available_time_band == "normal"
