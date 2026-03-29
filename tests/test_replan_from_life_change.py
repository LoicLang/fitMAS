from __future__ import annotations

import unittest
from datetime import date, datetime

from fitmas.adaptation_decision import AdaptationLevel, WeekMissionStatus
from fitmas.athlete_profile import AthleteProfileSnapshot
from fitmas.planning_window_resolution import resolve_planning_window
from fitmas import schema as s
from fitmas.replan_from_life_change import maybe_replan_from_life_change, maybe_replan_from_user_indication
from fitmas.time_context import build_time_context
from fitmas.user_indications import fallback_interpret_user_indication


def _profile() -> AthleteProfileSnapshot:
    return AthleteProfileSnapshot(
        user_id=7,
        primary_sports=("running",),
        primary_sport="running",
        level_by_sport={"running": "intermediate"},
        goals=("preparer un 10 km",),
        weekly_availability={
            "wednesday": ("Mercredi matin dispo",),
            "thursday": ("Jeudi matin dispo",),
        },
        equipment=("gps_watch",),
        constraints=(),
        preferences=("matin",),
        preferred_training_times=("morning",),
        coach_tone="direct",
        coach_style_notes="court",
        athlete_identity_summary="Loic court.",
        onboarding_completed=True,
    )


def _session(
    *,
    session_id: int,
    day: str,
    label: str,
    scheduled_date: datetime,
    session_type: str,
    title: str,
    duration_min: int,
    intensity: str,
    load_score: int,
    priority: str,
    flexibility: str = "stable",
    sport_type: str = "running",
) -> s.ScheduledSession:
    return s.ScheduledSession(
        id=session_id,
        user_id=7,
        day=day,
        label=label,
        scheduled_date=scheduled_date,
        source_plan_created_at=scheduled_date,
        sport_type=sport_type,
        session_type=session_type,
        session_title=title,
        session_goal="objectif",
        session_note="",
        session_description="",
        duration_min=duration_min,
        intensity=intensity,
        load_score=load_score,
        priority=priority,
        nutrition_focus="",
        flexibility=flexibility,
        completion_status="planned",
    )


class ReplanFromLifeChangeTest(unittest.TestCase):
    def test_micro_unavailability_moves_session_when_open_slot_exists(self) -> None:
        today = date(2026, 3, 24)
        today_session = _session(
            session_id=1,
            day="tuesday",
            label="Mar",
            scheduled_date=datetime(2026, 3, 24, 18, 0),
            session_type="tempo",
            title="Tempo run",
            duration_min=55,
            intensity="moderate",
            load_score=4,
            priority="Cle",
        )
        week_plan = type("WeekPlan", (), {"mesocycle_week": 2, "is_deload": False})()
        planning_decision = type(
            "PlanningDecision",
            (),
            {
                "planning_mode": "maintain_load",
                "weekly_target_tss": 220.0,
                "rationale": ("stabilite suffisante",),
            },
        )()

        decision = maybe_replan_from_life_change(
            user_text="Merde imprévu je peux pas ce soir",
            today=today,
            time_context=build_time_context("Europe/Paris", now=datetime(2026, 3, 24, 17, 0)),
            profile=_profile(),
            week_plan=week_plan,
            planning_decision=planning_decision,
            today_session=today_session,
            scheduled_sessions=[today_session],
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_scenario.mutation.mutation_type, "move_session")
        self.assertEqual(decision.selected_scenario.mutation.target_date, "2026-03-25")
        self.assertEqual(decision.selected_scenario.week_mission_status, WeekMissionStatus.UNCHANGED)
        self.assertIn("Mission hebdo : inchangée", decision.user_message)

    def test_key_session_without_clean_move_escalates_to_meso(self) -> None:
        today = date(2026, 3, 24)
        today_session = _session(
            session_id=1,
            day="tuesday",
            label="Mar",
            scheduled_date=datetime(2026, 3, 24, 18, 0),
            session_type="vo2",
            title="VO2 piste",
            duration_min=60,
            intensity="hard",
            load_score=5,
            priority="Cle",
        )
        block_next = _session(
            session_id=2,
            day="wednesday",
            label="Mer",
            scheduled_date=datetime(2026, 3, 25, 7, 0),
            session_type="easy",
            title="Footing",
            duration_min=40,
            intensity="easy",
            load_score=1,
            priority="Normal",
            flexibility="stable",
        )
        week_plan = type("WeekPlan", (), {"mesocycle_week": 2, "is_deload": False})()
        planning_decision = type(
            "PlanningDecision",
            (),
            {
                "planning_mode": "maintain_load",
                "weekly_target_tss": 220.0,
                "rationale": ("stabilite suffisante",),
            },
        )()
        base_profile = _profile()
        sparse_profile = AthleteProfileSnapshot(
            user_id=base_profile.user_id,
            primary_sports=base_profile.primary_sports,
            primary_sport=base_profile.primary_sport,
            level_by_sport=base_profile.level_by_sport,
            goals=base_profile.goals,
            weekly_availability={"tuesday": ("Mardi soir dispo",)},
            equipment=base_profile.equipment,
            constraints=base_profile.constraints,
            preferences=base_profile.preferences,
            preferred_training_times=base_profile.preferred_training_times,
            coach_tone=base_profile.coach_tone,
            coach_style_notes=base_profile.coach_style_notes,
            athlete_identity_summary=base_profile.athlete_identity_summary,
            onboarding_completed=base_profile.onboarding_completed,
        )

        decision = maybe_replan_from_life_change(
            user_text="Je peux pas ce soir finalement",
            today=today,
            time_context=build_time_context("Europe/Paris", now=datetime(2026, 3, 24, 17, 0)),
            profile=sparse_profile,
            week_plan=week_plan,
            planning_decision=planning_decision,
            today_session=today_session,
            scheduled_sessions=[today_session, block_next],
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_scenario.mutation.mutation_type, "lighten_day")
        self.assertEqual(decision.selected_scenario.adaptation_level, AdaptationLevel.MESO)
        self.assertEqual(decision.selected_scenario.week_mission_status, WeekMissionStatus.SOFTENED)
        self.assertIn("Mission hebdo : adoucie", decision.user_message)

    def test_explicit_requested_day_is_preferred_when_valid(self) -> None:
        today = date(2026, 3, 24)
        today_session = _session(
            session_id=1,
            day="tuesday",
            label="Mar",
            scheduled_date=datetime(2026, 3, 24, 18, 0),
            session_type="tempo",
            title="Tempo run",
            duration_min=55,
            intensity="moderate",
            load_score=4,
            priority="Cle",
        )
        week_plan = type("WeekPlan", (), {"mesocycle_week": 2, "is_deload": False})()
        planning_decision = type(
            "PlanningDecision",
            (),
            {
                "planning_mode": "maintain_load",
                "weekly_target_tss": 220.0,
                "rationale": ("stabilite suffisante",),
            },
        )()

        decision = maybe_replan_from_life_change(
            user_text="Je peux pas ce soir, mais jeudi matin oui",
            today=today,
            time_context=build_time_context("Europe/Paris", now=datetime(2026, 3, 24, 17, 0)),
            profile=_profile(),
            week_plan=week_plan,
            planning_decision=planning_decision,
            today_session=today_session,
            scheduled_sessions=[today_session],
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_scenario.mutation.mutation_type, "move_session")
        self.assertEqual(decision.selected_scenario.mutation.target_date, "2026-03-26")

    def test_fatigue_signal_prefers_minimum_effective_dose(self) -> None:
        today = date(2026, 3, 24)
        today_session = _session(
            session_id=1,
            day="tuesday",
            label="Mar",
            scheduled_date=datetime(2026, 3, 24, 18, 0),
            session_type="tempo",
            title="Tempo run",
            duration_min=50,
            intensity="moderate",
            load_score=4,
            priority="Cle",
        )
        week_plan = type("WeekPlan", (), {"mesocycle_week": 2, "is_deload": False})()
        planning_decision = type(
            "PlanningDecision",
            (),
            {
                "planning_mode": "maintain_load",
                "weekly_target_tss": 220.0,
                "rationale": ("stabilite suffisante",),
            },
        )()

        decision = maybe_replan_from_life_change(
            user_text="Je suis rincé aujourd'hui, jambes lourdes",
            today=today,
            time_context=build_time_context("Europe/Paris", now=datetime(2026, 3, 24, 12, 0)),
            profile=_profile(),
            week_plan=week_plan,
            planning_decision=planning_decision,
            today_session=today_session,
            scheduled_sessions=[today_session],
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_scenario.mutation.mutation_type, "replace_session")
        self.assertEqual(decision.selected_scenario.scenario_type, "minimum_dose")
        self.assertIn("version courte", decision.selected_scenario.mutation.new_title or "")

    def test_future_availability_constraint_can_replan_from_structured_indication(self) -> None:
        today = date(2026, 3, 29)
        tomorrow_session = _session(
            session_id=2,
            day="monday",
            label="Lun",
            scheduled_date=datetime(2026, 3, 30, 18, 0),
            session_type="tempo",
            title="Tempo run",
            duration_min=55,
            intensity="moderate",
            load_score=4,
            priority="Cle",
        )
        week_plan = type("WeekPlan", (), {"mesocycle_week": 2, "is_deload": False})()
        planning_decision = type(
            "PlanningDecision",
            (),
            {
                "planning_mode": "maintain_load",
                "weekly_target_tss": 220.0,
                "rationale": ("stabilite suffisante",),
            },
        )()
        indication = fallback_interpret_user_indication(
            "Je ne suis pas dispo demain soir",
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )
        self.assertIsNotNone(indication)
        resolution = resolve_planning_window(
            indication=indication,
            scheduled_sessions=[tomorrow_session],
            timezone_name="Europe/Paris",
            now=datetime(2026, 3, 29, 8, 0),
        )

        decision = maybe_replan_from_user_indication(
            indication=indication,
            resolution=resolution,
            today=today,
            profile=_profile(),
            week_plan=week_plan,
            planning_decision=planning_decision,
            today_session=None,
            scheduled_sessions=[tomorrow_session],
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_scenario.mutation.mutation_type, "move_session")
        self.assertEqual(decision.selected_scenario.mutation.target_date, "2026-04-01")


if __name__ == "__main__":
    unittest.main()
