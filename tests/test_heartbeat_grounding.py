from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-heartbeat-", suffix=".db"))

import fitmas.heartbeat as heartbeat
import fitmas.adaptation as adaptation
from fitmas import repository as repo, schema as s
from fitmas.adaptation import AdaptationResult
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.llm import MutationDecision
from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now


class HeartbeatGroundingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris", coach_name="FitMAS", coach_style="direct")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()
        heartbeat._LAST_PROACTIVE_GUARD_AT.clear()

    def test_weekly_review_prompt_mentions_actual_activities(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="cycling",
            title="Sortie velo",
            duration_min=35,
            distance_m=10000,
            elevation_m=0,
            perceived_load=3,
            note="",
            started_at=now - timedelta(days=1),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=20.0,
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("Activites reelles detectees sur 7 jours: 1", captured["prompt"])
        self.assertIn("Duree reelle totale: 35 min", captured["prompt"])

    def test_morning_briefing_mentions_yesterday_off_plan_activity(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": yesterday_key,
                    "label": day_label_fr(yesterday_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "technique",
                    "session_title": "Natation",
                    "session_goal": "Precision",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 60,
                    "intensity": "moderate",
                    "load_score": 3,
                    "priority": "Seance cle",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="running",
            title="Course off-plan",
            duration_min=30,
            distance_m=5000,
            elevation_m=0,
            perceived_load=3,
            note="",
            started_at=now - timedelta(days=1),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=24.0,
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertNotIn("activite reelle detectee", captured["prompt"].lower())

    def test_morning_briefing_mentions_yesterday_claimed_activity(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": yesterday_key,
                    "label": day_label_fr(yesterday_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "technique",
                    "session_title": "Natation",
                    "session_goal": "Precision",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 60,
                    "intensity": "moderate",
                    "load_score": 3,
                    "priority": "Seance cle",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        yesterday_iso = (now.date() - timedelta(days=1)).isoformat()
        repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "execution",
                    "key": f"claimed_activity_{yesterday_iso}_running",
                    "value": f"Activite declaree par l'utilisateur: running, 30 min, date {yesterday_iso}, non loggee.",
                    "confidence": 0.9,
                    "confirmed": True,
                    "source": "conversation",
                }
            ],
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertNotIn("activite declaree non loggee", captured["prompt"].lower())

    def test_morning_briefing_does_not_trust_done_without_evidence(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": yesterday_key,
                    "label": day_label_fr(yesterday_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "done",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "technique",
                    "session_title": "Natation",
                    "session_goal": "Precision",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertNotIn("statut a verifier", captured["prompt"].lower())
        self.assertNotIn("fait confirme", captured["prompt"].lower())

    def test_morning_briefing_adds_priority_question_when_yesterday_changes_week(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        two_days_ago_key = DAY_KEYS[(now.weekday() - 2) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": two_days_ago_key,
                    "label": day_label_fr(two_days_ago_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "easy",
                    "session_title": "Natation",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 40,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Support",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "cycling",
                    "session_type": "easy",
                    "session_title": "Vélo",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        self.db.add_all(
            [
                s.ScheduledSession(
                    user_id=self.user.id,
                    day=two_days_ago_key,
                    label=day_label_fr(two_days_ago_key, capitalize=True),
                    scheduled_date=(now - timedelta(days=2)).replace(hour=7, minute=0, second=0, microsecond=0, tzinfo=None),
                    sport_type="swimming",
                    session_type="easy",
                    session_title="Natation",
                    session_goal="Bouger",
                    session_note="",
                    session_description="",
                    duration_min=40,
                    intensity="easy",
                    load_score=1,
                    priority="Support",
                    nutrition_focus="",
                    flexibility="stable",
                    completion_status="planned",
                ),
                s.ScheduledSession(
                    user_id=self.user.id,
                    day=yesterday_key,
                    label=day_label_fr(yesterday_key, capitalize=True),
                    scheduled_date=(now - timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0, tzinfo=None),
                    sport_type="running",
                    session_type="tempo",
                    session_title="Course clé",
                    session_goal="Stimulus",
                    session_note="",
                    session_description="",
                    duration_min=60,
                    intensity="moderate",
                    load_score=4,
                    priority="High",
                    nutrition_focus="",
                    flexibility="stable",
                    completion_status="planned",
                ),
            ]
        )
        self.db.commit()
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("clarification prioritaire", captured["prompt"].lower())
        self.assertIn("tu l'as faite ou pas", captured["prompt"].lower())

    def test_morning_briefing_can_attach_hidden_calibration_need(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        tomorrow_key = DAY_KEYS[(now.weekday() + 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        self.db.add(
            s.ScheduledSession(
                user_id=self.user.id,
                day=tomorrow_key,
                label=day_label_fr(tomorrow_key, capitalize=True),
                scheduled_date=(now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0, tzinfo=None),
                sport_type="running",
                session_type="tempo",
                session_title="Tempo",
                session_goal="Stimulus",
                session_note="",
                session_description="",
                duration_min=55,
                intensity="hard",
                load_score=4,
                priority="Seance cle",
                nutrition_focus="",
                flexibility="stable",
                completion_status="planned",
            )
        )
        self.user.onboarding_status = "completed"
        self.user.weekly_structure_notes = "mardi matin fiable"
        self.db.commit()
        repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "calibration_need",
                    "key": "availability_window",
                    "value": (
                        '{"id":"availability_window:tomorrow_window",'
                        '"need_type":"availability_window",'
                        '"topic":"availability_window",'
                        '"status":"open",'
                        '"why_now":"Demain porte une seance utile.",'
                        '"priority":"high",'
                        '"source":"heartbeat_morning",'
                        '"channel_hint":"telegram",'
                        '"created_at":"2026-03-28T08:00:00+00:00",'
                        '"expires_at":"2026-04-20T08:00:00+00:00",'
                        '"last_prompted_at":"2026-03-28T08:00:00+00:00",'
                        '"context":{"day":"%s"},'
                        '"allowed_answers":["morning","evening","both","none"],'
                        '"write_targets":["weekly_availability"],'
                        '"followup_policy":"single_followup"}'
                    ) % tomorrow_key,
                    "confidence": 0.95,
                    "confirmed": True,
                    "source": "heartbeat_morning",
                }
            ],
        )
        original_llm = heartbeat._llm_generate
        try:
            heartbeat._llm_generate = lambda *args, **kwargs: "Bonjour. Aujourd'hui on garde du propre. Je veux juste verrouiller un point pour demain: tu le tiens plutot le matin ou le soir ?"
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertIsNotNone(draft)
        self.assertTrue(draft.memory_updates)
        self.assertEqual(draft.memory_updates[0]["category"], "calibration_need")

    def test_morning_briefing_does_not_repeat_stable_constraint_fact(self) -> None:
        _, _ = self._create_plan_with_today_session()
        repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "constraint",
                    "key": "pool_fixed_slots",
                    "value": "Piscine fixee lundi et jeudi matin a 7h.",
                    "confidence": 0.95,
                    "confirmed": True,
                    "source": "conversation",
                    "affects": ["planning", "conversation", "heartbeat"],
                }
            ],
        )

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["system"] = system
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertNotIn("Piscine fixee lundi et jeudi matin a 7h.", captured["system"])

    def test_llm_generate_blocks_readonly_commit_claims(self) -> None:
        original_generate = heartbeat.generate_heartbeat_text
        original_request_text = getattr(heartbeat, "request_text", None)
        try:
            heartbeat.generate_heartbeat_text = (
                lambda *args, **kwargs: "Regarde ton app demain matin, j'ai ajuste le planning."
            )
            heartbeat.request_text = lambda **kwargs: "BLOCK"
            text = heartbeat._llm_generate("system", "prompt", pipeline="heartbeat_briefing")
        finally:
            heartbeat.generate_heartbeat_text = original_generate
            if original_request_text is not None:
                heartbeat.request_text = original_request_text

        self.assertIsNone(text)

    def test_llm_generate_allows_ambiguous_readonly_claim_when_judge_allows(self) -> None:
        original_generate = heartbeat.generate_heartbeat_text
        original_request_text = getattr(heartbeat, "request_text", None)
        try:
            heartbeat.generate_heartbeat_text = (
                lambda *args, **kwargs: "J'ai ajuste mon angle : je te propose de garder le footing easy."
            )
            heartbeat.request_text = lambda **kwargs: "ALLOW"
            text = heartbeat._llm_generate("system", "prompt", pipeline="heartbeat_review")
        finally:
            heartbeat.generate_heartbeat_text = original_generate
            if original_request_text is not None:
                heartbeat.request_text = original_request_text

        self.assertEqual(text, "J'ai ajuste mon angle : je te propose de garder le footing easy.")

    def test_llm_generate_judges_future_agency_claims(self) -> None:
        original_generate = heartbeat.generate_heartbeat_text
        original_request_text = getattr(heartbeat, "request_text", None)
        try:
            heartbeat.generate_heartbeat_text = (
                lambda *args, **kwargs: "La semaine prochaine, on recentre sur l'eau et on allege le renfo."
            )
            heartbeat.request_text = lambda **kwargs: "BLOCK"
            text = heartbeat._llm_generate("system", "prompt", pipeline="heartbeat_review")
        finally:
            heartbeat.generate_heartbeat_text = original_generate
            if original_request_text is not None:
                heartbeat.request_text = original_request_text

        self.assertIsNone(text)

    def test_llm_generate_judges_every_heartbeat_message(self) -> None:
        original_generate = heartbeat.generate_heartbeat_text
        original_request_text = getattr(heartbeat, "request_text", None)
        try:
            heartbeat.generate_heartbeat_text = (
                lambda *args, **kwargs: "Footing easy ce matin, rien a forcer."
            )
            calls: list[dict] = []

            def fake_judge(**kwargs):
                calls.append(kwargs)
                return "ALLOW"

            heartbeat.request_text = fake_judge
            text = heartbeat._llm_generate("system", "prompt", pipeline="heartbeat_briefing")
        finally:
            heartbeat.generate_heartbeat_text = original_generate
            if original_request_text is not None:
                heartbeat.request_text = original_request_text

        self.assertEqual(text, "Footing easy ce matin, rien a forcer.")
        self.assertEqual(len(calls), 1)

    def test_morning_briefing_includes_recent_proactive_messages_for_novelty(self) -> None:
        _, _ = self._create_plan_with_today_session()
        self.db.add_all(
            [
                # Chantier 0 (2 mai 2026): TTL 48h applique a `_recent_proactive_context`.
                # `hours=30` => dans la fenetre 48h (donc injecte) mais hors today
                # local midnight (donc pas compte par le daily cap a 2 proactives).
                s.CoachMessage(
                    user_id=self.user.id,
                    role="agent",
                    text="Bonjour. Journee flexible. Priorite: souplesse.",
                    proactive=True,
                    created_at=(datetime.now(dt_timezone.utc) - timedelta(hours=30)).replace(tzinfo=None),
                ),
                s.CoachMessage(
                    user_id=self.user.id,
                    role="agent",
                    text="Bonjour. Je garde de l'air a la semaine.",
                    proactive=True,
                    created_at=(datetime.now(dt_timezone.utc) - timedelta(hours=30, minutes=5)).replace(tzinfo=None),
                ),
            ]
        )
        self.db.commit()

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["system"] = system
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("cherche de la nouveauté utile", captured["system"].lower())
        self.assertIn("derniers messages proactifs a ne pas recycler", captured["prompt"].lower())
        self.assertIn("journee flexible", captured["prompt"].lower())

    def test_weekly_review_prompt_mentions_claimed_activities(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        today_iso = now.date().isoformat()
        repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "execution",
                    "key": f"claimed_activity_{today_iso}_running",
                    "value": f"Activite declaree par l'utilisateur: running, 30 min, date {today_iso}, non loggee.",
                    "confidence": 0.9,
                    "confirmed": True,
                    "source": "conversation",
                }
            ],
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("Activites declarees non loggees sur 7 jours: 1", captured["prompt"])
        self.assertIn("Duree declaree totale: 30 min", captured["prompt"])

    def test_weekly_review_prompt_mentions_active_health_fact(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        repo.upsert_facts(
            self.db,
            self.user.id,
            [
                {
                    "category": "health",
                    "key": "reported_health_general",
                    "value": "Etat de sante general degrade. type illness. severite moderate. source: Je suis malade comme un chien.",
                    "confidence": 0.95,
                    "confirmed": True,
                    "source": "conversation",
                    "affects": ["planning", "conversation", "heartbeat"],
                }
            ],
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["system"] = system
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("faits actifs a prendre en compte", captured["system"].lower())
        self.assertIn("etat de sante general degrade", captured["system"].lower())

    def test_weekly_review_prompt_mentions_weekly_health_highlight_from_transcript(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        repo.add_conversation_turn(
            self.db,
            user_id=self.user.id,
            user_message="Je suis malade comme un chien cette semaine j'ai rien fait",
            assistant_message="Repos complet. On coupe propre.",
            response_mode="health_adaptation",
            extraction_confidence=0.92,
            day_updated=None,
            mutation_type="lighten_day",
            mutation_applied=True,
            pending_confirmation=False,
            pending_confirmation_id=None,
            decision_json="{}",
            context={},
            memory_writes=[],
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("evenements explicatifs de la semaine", captured["prompt"].lower())
        self.assertIn("je suis malade comme un chien", captured["prompt"].lower())

    def test_signal_check_can_surface_adaptation_suggestion_without_apply(self) -> None:
        self._create_plan_with_today_session()
        original_tsb = adaptation.check_and_adapt_tsb
        original_missed = adaptation.check_and_adapt_missed
        original_collect = heartbeat.collect_signals
        original_gate = heartbeat.heartbeat_evaluation.evaluate_proactive_gate
        try:
            heartbeat.heartbeat_evaluation.evaluate_proactive_gate = lambda *args, **kwargs: SimpleNamespace(
                allowed=True,
                reason=None,
            )
            adaptation.check_and_adapt_tsb = lambda *args, **kwargs: AdaptationResult(
                trigger_type="tsb_alert",
                decisions=[
                    MutationDecision(
                        mutation_type="lighten_day",
                        target_session_id=1,
                        rationale="Charge haute.",
                        fitmas_message="",
                    )
                ],
                message="Je te proposerais d'alleger la prochaine seance.",
                applied=False,
            )
            adaptation.check_and_adapt_missed = lambda *args, **kwargs: None
            heartbeat.collect_signals = lambda *args, **kwargs: []
            draft = heartbeat.signal_check()
        finally:
            adaptation.check_and_adapt_tsb = original_tsb
            adaptation.check_and_adapt_missed = original_missed
            heartbeat.collect_signals = original_collect
            heartbeat.heartbeat_evaluation.evaluate_proactive_gate = original_gate

        events = self.db.query(s.PlanMutationEventRecord).all()

        self.assertIsNotNone(draft)
        self.assertIn("proposerais", draft.text.lower())
        self.assertEqual(events, [])

    def test_morning_briefing_prefers_scheduled_session_over_legacy_day_plan(self) -> None:
        _, today_session = self._create_plan_with_today_session()
        plan = repo.get_active_plan(self.db, self.user.id)
        day_row = repo.get_day_plan(self.db, plan.id, today_session.day)
        day_row.session_title = "Legacy footing plan"
        day_row.session_goal = "Legacy goal"
        today_session.session_title = "Natation app truth"
        today_session.session_goal = "Souplesse et sensations"
        today_session.sport_type = "swimming"
        today_session.priority = "Repere fort"
        self.db.commit()

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("Source de verite planning: calendrier date reel / app.", captured["prompt"])
        self.assertIn("Natation app truth", captured["prompt"])
        self.assertNotIn("Legacy footing plan", captured["prompt"])

    def test_morning_briefing_keeps_running_without_active_plan(self) -> None:
        plan, today_session = self._create_plan_with_today_session()
        self.db.delete(plan)
        self.db.commit()

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn(today_session.session_title, captured["prompt"])
        self.assertIn("Source de verite planning: calendrier date reel / app.", captured["prompt"])

    def test_weekly_review_prefers_scheduled_sessions_over_legacy_plan(self) -> None:
        _, today_session = self._create_plan_with_today_session()
        plan = repo.get_active_plan(self.db, self.user.id)
        day_row = repo.get_day_plan(self.db, plan.id, today_session.day)
        day_row.session_title = "Legacy footing plan"
        today_session.session_title = "Natation app truth"
        today_session.sport_type = "swimming"
        self.db.commit()

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("Source de verite planning: calendrier date reel / app.", captured["prompt"])
        self.assertIn("Natation app truth", captured["prompt"])
        self.assertNotIn("Legacy footing plan", captured["prompt"])

    def test_morning_briefing_does_not_fall_back_to_legacy_yesterday_day_plan(self) -> None:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        yesterday_key = DAY_KEYS[(now.weekday() - 1) % 7]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": yesterday_key,
                    "label": day_label_fr(yesterday_key, capitalize=True),
                    "sport_type": "swimming",
                    "session_type": "technique",
                    "session_title": "Legacy yesterday swim",
                    "session_goal": "Precision",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 60,
                    "intensity": "moderate",
                    "load_score": 2,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing du jour",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                },
            ],
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertNotIn("Legacy yesterday swim", captured["prompt"])

    def test_weekly_review_surfaces_offplan_swimming_entry(self) -> None:
        """Chantier 2bis: weekly_review pre-digests deterministic facts so the
        LLM gets the offplan swim by sport+day instead of zero-natation."""
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        # Offplan swim: not linked to any ScheduledSession.
        repo.add_activity(
            self.db,
            user_id=self.user.id,
            source="manual",
            sport_type="swimming",
            title="Nage libre piscine",
            duration_min=45,
            distance_m=2000,
            elevation_m=0,
            perceived_load=3,
            note="",
            started_at=now - timedelta(days=2),
            matched_day=None,
            match_reason="",
            avg_hr=None,
            avg_speed=None,
            tss=30.0,
        )
        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["system"] = system
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.weekly_review()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        # Digest block must surface the swim with offplan marker.
        self.assertIn("Lecture de la semaine", captured["prompt"])
        self.assertIn("swimming", captured["prompt"])
        self.assertIn("(offplan)", captured["prompt"])
        # Anti-hallu rule must be present in the system prompt.
        self.assertIn("zero <sport>", captured["system"].lower().replace("\u00ab", "").replace("\u00bb", "").replace('"', ""))

    def test_morning_briefing_surfaces_pending_open_question_from_last_agent(self) -> None:
        """Chantier 3: if the last agent message ended on an open question and
        the user did not write since, the next morning briefing prompt must
        surface the question so the coach doesn't drop the thread."""
        _, _ = self._create_plan_with_today_session()
        # Last agent message ends on an open question, no later user reply.
        self.db.add(
            s.CoachMessage(
                user_id=self.user.id,
                role="agent",
                text="Je vois que tu as saute la natation lundi. Qu'est-ce qui s'est passe ?",
                proactive=True,
                created_at=(datetime.now(dt_timezone.utc) - timedelta(days=1)).replace(tzinfo=None),
            )
        )
        self.db.commit()

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertIn("Question ouverte de ton dernier message proactif", captured["prompt"])
        self.assertIn("Qu'est-ce qui s'est passe ?", captured["prompt"])

    def test_morning_briefing_omits_open_question_marker_when_user_already_replied(self) -> None:
        _, _ = self._create_plan_with_today_session()
        agent_at = (datetime.now(dt_timezone.utc) - timedelta(days=1)).replace(tzinfo=None)
        self.db.add_all(
            [
                s.CoachMessage(
                    user_id=self.user.id,
                    role="agent",
                    text="Qu'est-ce qui s'est passe lundi ?",
                    proactive=True,
                    created_at=agent_at,
                ),
                s.CoachMessage(
                    user_id=self.user.id,
                    role="user",
                    text="J'ai eu un imprevu",
                    proactive=False,
                    created_at=agent_at + timedelta(hours=1),
                ),
            ]
        )
        self.db.commit()

        captured: dict[str, str] = {}
        original_llm = heartbeat._llm_generate
        try:
            def fake_llm(system: str, prompt: str, *, allow_no_send: bool = True, **_kwargs):
                captured["prompt"] = prompt
                return "ok"

            heartbeat._llm_generate = fake_llm
            draft = heartbeat.morning_briefing()
        finally:
            heartbeat._llm_generate = original_llm

        self.assertEqual(draft.text, "ok")
        self.assertNotIn("Question ouverte de ton dernier message proactif", captured["prompt"])

    def _create_plan_with_today_session(self) -> tuple[s.WeeklyPlan, s.ScheduledSession]:
        now = get_local_now(self.user.timezone)
        today_key = DAY_KEYS[now.weekday()]
        plan = repo.replace_plan(
            self.db,
            self.user.id,
            intention="test",
            summary="test",
            timezone_name=self.user.timezone,
            days=[
                {
                    "day": today_key,
                    "label": day_label_fr(today_key, capitalize=True),
                    "sport_type": "running",
                    "session_type": "easy",
                    "session_title": "Footing",
                    "session_goal": "Bouger",
                    "session_note": "",
                    "session_description": "",
                    "duration_min": 45,
                    "intensity": "easy",
                    "load_score": 1,
                    "priority": "Normal",
                    "nutrition_focus": "",
                    "flexibility": "stable",
                    "completion_status": "planned",
                }
            ],
        )
        session = repo.get_today_scheduled_session(self.db, self.user.id, timezone_name=self.user.timezone)
        self.assertIsNotNone(session)
        return plan, session


if __name__ == "__main__":
    unittest.main()
