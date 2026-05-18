from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("FITMAS_DB_PATH", tempfile.mktemp(prefix="fitmas-pending-bridge-", suffix=".db"))

from fitmas import llm, repository as repo, schema as s
from fitmas.db import Base, SessionLocal, engine, init_db
from fitmas.decision import CoachUnderstanding, PendingResolution
from fitmas.decision.reply_request import ReplyResult
from fitmas.legacy import conversation_pending_bridge
from fitmas.legacy.coach_decision_artifact import legacy_decision_artifact_from_raw
from fitmas.llm import CoachDecision
from fitmas.mutation_permissions import (
    default_confirmation_expiry,
    serialize_plan_patch_choice_confirmation,
    serialize_plan_patch_confirmation,
)
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.plan_patch_candidates import PlanPatchCandidate
from fitmas.time_context import DAY_KEYS, day_label_fr


class _SpyPendingComposer:
    def __init__(self, text: str):
        self.text = text
        self.outcomes = []

    def compose(self, outcome, context, *, user_text: str = "", grounding_facts: tuple[str, ...] = ()):
        self.outcomes.append(outcome)
        return ReplyResult(text=self.text, verified=True, fallback_used=False, reason=None)


class ConversationPendingBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        init_db()
        self.db = SessionLocal()
        self.user = s.User(name="Loic", timezone="Europe/Paris")
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self) -> None:
        self.db.close()

    def test_accept_pending_plan_patch_applies_patch_after_typed_resolution_and_recheck(self) -> None:
        session = self._scheduled_session()
        target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je deplace la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=target_date,
                        rationale="Demande confirmee.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="no_change",
            rationale="acceptation pending comprise",
            fitmas_message="C'est confirme. Je l'applique.",
            pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
        )

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=legacy_decision_artifact_from_raw(decision),
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="oui confirme",
            verify_pending_accept_resolution_fn=lambda **kwargs: "accept_pending",
        )

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_accepted")
        self.assertTrue(outcome.mutation_applied)
        self.assertEqual(refreshed.scheduled_date.date().isoformat(), target_date)
        self.assertEqual(refreshed_pending.status, "accepted")

    def test_accept_pending_mismatch_keeps_pending_open(self) -> None:
        session = self._scheduled_session()
        target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je deplace la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=target_date,
                        rationale="Demande a confirmer.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="reply",
            rationale="acceptation surestimee par le modele principal",
            fitmas_message="Je le fais.",
            pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
        )

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=legacy_decision_artifact_from_raw(decision),
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="j'attends",
            verify_pending_accept_resolution_fn=lambda **kwargs: "ignore",
        )

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_ignore")
        self.assertTrue(outcome.pending_confirmation)
        self.assertEqual(outcome.pending_confirmation_id, pending.id)
        self.assertNotEqual(refreshed.scheduled_date.date().isoformat(), target_date)
        self.assertEqual(refreshed_pending.status, "pending")

    def test_pending_recheck_prompt_treats_coach_judgment_condition_as_acceptance(self) -> None:
        captured: dict[str, str] = {}

        def fake_request_json(**kwargs):
            captured["system"] = kwargs["system"]
            return {
                "resolution_type": "accept_pending",
                "confidence": 0.95,
                "reason": "validation conditionnelle explicite",
            }

        result = conversation_pending_bridge.verify_pending_accept_resolution(
            user_text="oui je confirme si tu penses que c'est propre",
            pending_resolution=conversation_pending_bridge.PendingResolutionArtifact(
                type="accept_pending",
                reason="confirmation",
                source="coach_understanding",
            ),
            pending_confirmation=SimpleNamespace(
                id=1,
                mutation_type="plan_patch",
                reason="a confirmer",
                summary="Deplacer recuperation",
                source_text="deplace la recuperation",
                decision_json="{}",
            ),
            request_json_fn=fake_request_json,
        )

        self.assertEqual(result, "accept_pending")
        self.assertIn("si tu penses que c'est propre", captured["system"])

    def test_canonical_understanding_can_drive_pending_accept_when_enabled(self) -> None:
        session = self._scheduled_session()
        target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je deplace la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=target_date,
                        rationale="Demande confirmee.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="no_change",
            rationale="legacy decision sans pending",
            fitmas_message="OK.",
            pending_resolution=None,
        )
        understanding = CoachUnderstanding(
            intent="pending_response",
            confidence=0.92,
            user_summary="Le user confirme le pending.",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=PendingResolution(
                type="accept_pending",
                reason="confirmation explicite",
                selected_candidate_id=None,
                requested_changes=None,
                question=None,
            ),
            clarification_need=None,
        )

        old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
        os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "1"
        try:
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                canonical_understanding=understanding,
                pending_confirmation=pending,
                user_text="vas-y",
                verify_pending_accept_resolution_fn=lambda **kwargs: "accept_pending",
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_accepted")
        self.assertEqual(refreshed.scheduled_date.date().isoformat(), target_date)
        self.assertEqual(refreshed_pending.status, "accepted")

    def test_canonical_understanding_pending_resolution_wins_when_flag_enabled(self) -> None:
        session = self._scheduled_session()
        target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je deplace la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=target_date,
                        rationale="Demande a confirmer.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="no_change",
            rationale="legacy thinks accept",
            fitmas_message="legacy must not decide",
            pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
        )
        understanding = CoachUnderstanding(
            intent="pending_response",
            confidence=0.9,
            user_summary="Le user refuse finalement.",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=PendingResolution(
                type="reject_pending",
                reason="refus explicite",
                selected_candidate_id=None,
                requested_changes=None,
                question=None,
            ),
            clarification_need=None,
        )

        old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
        os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "1"
        try:
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                canonical_understanding=understanding,
                pending_confirmation=pending,
                user_text="non",
                verify_pending_accept_resolution_fn=lambda **kwargs: "reject_pending",
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        refreshed_pending = self.db.get(s.PendingMutationConfirmation, pending.id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_rejected")
        self.assertFalse(outcome.mutation_applied)
        self.assertNotEqual(refreshed.scheduled_date.date().isoformat(), target_date)
        self.assertEqual(refreshed_pending.status, "rejected")

    def test_pending_from_understanding_flag_falls_back_when_canonical_has_no_pending(self) -> None:
        session = self._scheduled_session()
        target_date = (session.scheduled_date.date() + timedelta(days=2)).isoformat()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je deplace la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=target_date,
                        rationale="Demande confirmee.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="no_change",
            rationale="legacy accept",
            fitmas_message="legacy accept",
            pending_resolution=llm.AcceptPendingResolution(type="accept_pending"),
        )
        understanding = CoachUnderstanding(
            intent="general_answer",
            confidence=0.7,
            user_summary="pas de pending canonical",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=None,
            clarification_need=None,
        )

        old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
        os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "1"
        try:
            outcome = conversation_pending_bridge.apply_pending_resolution(
                db=self.db,
                user=self.user,
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                canonical_understanding=understanding,
                pending_confirmation=pending,
                user_text="oui",
                verify_pending_accept_resolution_fn=lambda **kwargs: "accept_pending",
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_accepted")
        self.assertTrue(outcome.mutation_applied)
        self.assertEqual(refreshed.scheduled_date.date().isoformat(), target_date)

    def test_pending_from_understanding_default_on_when_artifact_exists(self) -> None:
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy sans pending",
            fitmas_message="ok",
            pending_resolution=None,
        )
        understanding = CoachUnderstanding(
            intent="pending_response",
            confidence=0.92,
            user_summary="confirmation",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=PendingResolution(
                type="accept_pending",
                reason="ok",
                selected_candidate_id=None,
                requested_changes=None,
                question=None,
            ),
            clarification_need=None,
        )

        old_flag = os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
        try:
            artifact = conversation_pending_bridge.pending_resolution_from_sources(
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                canonical_understanding=understanding,
            )
        finally:
            if old_flag is not None:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.source, "coach_understanding")
        self.assertEqual(artifact.type, "accept_pending")

    def test_pending_from_understanding_can_be_disabled(self) -> None:
        decision = CoachDecision(
            response_type="reply",
            rationale="legacy pending",
            fitmas_message="ok",
            pending_resolution=llm.IgnorePendingResolution(type="ignore"),
        )
        understanding = CoachUnderstanding(
            intent="pending_response",
            confidence=0.92,
            user_summary="confirmation",
            extracted_signals=(),
            requested_change=None,
            pending_resolution=PendingResolution(
                type="accept_pending",
                reason="ok",
                selected_candidate_id=None,
                requested_changes=None,
                question=None,
            ),
            clarification_need=None,
        )

        old_flag = os.environ.get("FITMAS_PENDING_FROM_UNDERSTANDING")
        os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = "0"
        try:
            artifact = conversation_pending_bridge.pending_resolution_from_sources(
                decision_artifact=legacy_decision_artifact_from_raw(decision),
                canonical_understanding=understanding,
            )
        finally:
            if old_flag is None:
                os.environ.pop("FITMAS_PENDING_FROM_UNDERSTANDING", None)
            else:
                os.environ["FITMAS_PENDING_FROM_UNDERSTANDING"] = old_flag

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.source, "coach_decision")
        self.assertEqual(artifact.type, "ignore")

    def test_pending_choice_applies_selected_candidate(self) -> None:
        session = self._scheduled_session()
        target_date = (session.scheduled_date.date() + timedelta(days=4)).isoformat()
        candidate = PlanPatchCandidate(
            id="move_friday",
            patches=(
                PlanPatch(
                    coach_message="Option vendredi.",
                    operations=(
                        PlanPatchOperation(
                            operation_type="move_session",
                            target_session_id=session.id,
                            target_date=target_date,
                            rationale="Option choisie.",
                        ),
                    ),
                ),
            ),
            rationale="Deplacer la seance a vendredi.",
            expected_tradeoff="Garde le volume.",
            confidence=0.8,
            assumptions=(),
            risk_notes=(),
            created_from_plan_id="plan_current",
            created_from_plan_version=1,
        )
        pending = repo.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="medium",
            reason="choix utilisateur",
            mutation_type="plan_patch_choice",
            summary="move_friday",
            source_text="test",
            decision_json=serialize_plan_patch_choice_confirmation((candidate,)),
            expires_at=default_confirmation_expiry(),
        )
        decision = CoachDecision(
            response_type="no_change",
            rationale="choix compris",
            fitmas_message="Je prends vendredi.",
            pending_resolution=llm.AcceptPendingResolution(
                type="accept_pending",
                selected_candidate_id="move_friday",
            ),
        )

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=legacy_decision_artifact_from_raw(decision),
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="vendredi",
            verify_pending_accept_resolution_fn=lambda **kwargs: "accept_pending",
        )

        self.db.expire_all()
        refreshed = repo.get_scheduled_session(self.db, self.user.id, session.id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.response_mode, "pending_choice_accepted")
        self.assertEqual(refreshed.scheduled_date.date().isoformat(), target_date)

    def test_ignore_pending_reply_comes_from_composer_not_legacy_message(self) -> None:
        session = self._scheduled_session()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je deplace la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="move_session",
                        target_session_id=session.id,
                        target_date=(session.scheduled_date.date() + timedelta(days=2)).isoformat(),
                        rationale="Demande a confirmer.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="reply",
            rationale="ignore pending",
            fitmas_message="LEGACY MESSAGE MUST NOT LEAK",
            pending_resolution=llm.IgnorePendingResolution(type="ignore"),
        )
        composer = _SpyPendingComposer("Composer garde la proposition ouverte.")

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=legacy_decision_artifact_from_raw(decision),
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="j'attends",
            decision_reply_composer=composer,
        )

        assert outcome is not None
        self.assertEqual(outcome.reply_text, "Composer garde la proposition ouverte.")
        self.assertEqual(composer.outcomes[0].kind, "plan_pending")
        self.assertNotIn("LEGACY", outcome.reply_text)

    def test_reject_pending_reply_comes_from_composer_not_legacy_message(self) -> None:
        session = self._scheduled_session()
        pending = self._pending_plan_patch(
            PlanPatch(
                coach_message="Je reduis la seance.",
                operations=(
                    PlanPatchOperation(
                        operation_type="update_session",
                        target_session_id=session.id,
                        new_duration_min=25,
                        rationale="Demande a refuser.",
                    ),
                ),
            )
        )
        decision = CoachDecision(
            response_type="reply",
            rationale="reject pending",
            fitmas_message="LEGACY MESSAGE MUST NOT LEAK",
            pending_resolution=llm.RejectPendingResolution(type="reject_pending"),
        )
        composer = _SpyPendingComposer("Composer refuse sans mutation.")

        outcome = conversation_pending_bridge.apply_pending_resolution(
            db=self.db,
            user=self.user,
            decision_artifact=legacy_decision_artifact_from_raw(decision),
            canonical_understanding=None,
            pending_confirmation=pending,
            user_text="non",
            verify_pending_accept_resolution_fn=lambda **kwargs: "reject_pending",
            decision_reply_composer=composer,
        )

        assert outcome is not None
        self.assertEqual(outcome.response_mode, "pending_rejected")
        self.assertEqual(outcome.reply_text, "Composer refuse sans mutation.")
        self.assertEqual(composer.outcomes[0].kind, "answer")

    def _pending_plan_patch(self, patch: PlanPatch) -> s.PendingMutationConfirmation:
        return repo.create_pending_mutation_confirmation(
            self.db,
            user_id=self.user.id,
            impact_level="high",
            reason="test pending",
            mutation_type="plan_patch",
            summary="pending patch",
            source_text="test",
            decision_json=serialize_plan_patch_confirmation(patch),
            expires_at=default_confirmation_expiry(),
        )

    def _scheduled_session(self) -> s.ScheduledSession:
        now = datetime.now(UTC).replace(tzinfo=None)
        day = DAY_KEYS[now.weekday()]
        session = s.ScheduledSession(
            user_id=self.user.id,
            day=day,
            label=day_label_fr(day, capitalize=True),
            scheduled_date=now.replace(hour=8, minute=0, second=0, microsecond=0),
            sport_type="running",
            session_type="easy",
            session_title="Footing facile",
            session_goal="Reprendre",
            duration_min=40,
            intensity="easy",
            load_score=2,
            priority="Normal",
            nutrition_focus="",
            flexibility="stable",
            completion_status="planned",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session


if __name__ == "__main__":
    unittest.main()
