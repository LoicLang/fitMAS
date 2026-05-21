from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fitmas.domain.planning.models import PlanningCandidateSet, ResolvedPlanChange
from fitmas.plan_patch import PlanPatch, PlanPatchOperation
from fitmas.domain.planning.candidates import PlanPatchCandidate

_PLAN_ID = "plan_current"
_PLAN_VERSION = 1
_USER_SAFE_PATCH_MESSAGE = "Je te propose un ajustement prudent, a confirmer avant application."


class PlanCandidateBuilder:
    def __init__(self, context: Any):
        self._context = context

    def build(self, resolved_change: ResolvedPlanChange) -> PlanningCandidateSet:
        if resolved_change.kind == "constraint_window" and resolved_change.source.kind == "availability_window":
            return self._build_constraint_window_candidates(resolved_change)
        if resolved_change.kind == "replace" and resolved_change.source.kind == "sport_window":
            return self._build_sport_window_replace_candidates(resolved_change)
        patch = self._patch_for_change(resolved_change)
        if patch is None:
            return PlanningCandidateSet(candidates=(), backend_candidate_patches={})
        ref = _candidate_ref(resolved_change, patch)
        candidate = PlanPatchCandidate(
            id=ref,
            patches=(),
            rationale=resolved_change.reason or "Adaptation planning demandee.",
            expected_tradeoff="Option backend construite puis evaluee avant application.",
            confidence=0.85,
            assumptions=(),
            risk_notes=resolved_change.requested_change.risk_signals,
            created_from_plan_id=_PLAN_ID,
            created_from_plan_version=_PLAN_VERSION,
            candidate_ref=ref,
        )
        return PlanningCandidateSet(candidates=(candidate,), backend_candidate_patches={ref: patch})

    def _build_sport_window_replace_candidates(self, resolved_change: ResolvedPlanChange) -> PlanningCandidateSet:
        patches = self._replace_patches_for_sport_window(resolved_change)
        candidates = tuple(
            PlanPatchCandidate(
                id=ref,
                patches=(),
                rationale=resolved_change.reason or "Sport indisponible dans une fenetre typee.",
                expected_tradeoff="Remplacer seulement les seances du sport indisponible, puis evaluer la semaine.",
                confidence=0.85,
                assumptions=(),
                risk_notes=resolved_change.requested_change.risk_signals,
                created_from_plan_id=_PLAN_ID,
                created_from_plan_version=_PLAN_VERSION,
                candidate_ref=ref,
            )
            for ref in patches
        )
        return PlanningCandidateSet(candidates=candidates, backend_candidate_patches=patches)

    def _build_constraint_window_candidates(self, resolved_change: ResolvedPlanChange) -> PlanningCandidateSet:
        patch = self._constraint_window_move_after_patch(resolved_change)
        if patch is None:
            return PlanningCandidateSet(candidates=(), backend_candidate_patches={})
        source = resolved_change.source
        ref = f"backend:constraint_window:{source.starts_on.isoformat()}:{source.ends_on.isoformat()}:move_after"
        candidate = PlanPatchCandidate(
            id=ref,
            patches=(),
            rationale=resolved_change.reason or "Fenetre d'indisponibilite a adapter.",
            expected_tradeoff="Deplacer les seances touchees apres la fenetre, en gardant l'ordre, avec confirmation.",
            confidence=0.75,
            assumptions=("Fenetre indisponible issue d'une reference typee.",),
            risk_notes=tuple(dict.fromkeys((*resolved_change.requested_change.risk_signals, "multi_day"))),
            created_from_plan_id=_PLAN_ID,
            created_from_plan_version=_PLAN_VERSION,
            candidate_ref=ref,
        )
        return PlanningCandidateSet(candidates=(candidate,), backend_candidate_patches={ref: patch})

    def _constraint_window_move_after_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        source = resolved_change.source
        starts_on = source.starts_on
        ends_on = source.ends_on
        if source.availability != "unavailable" or starts_on is None or ends_on is None:
            return None
        affected = _affected_training_sessions(self._context, starts_on=starts_on, ends_on=ends_on)
        if not affected:
            return None
        targets = _open_target_dates_after_window(self._context, starts_after=ends_on, count=len(affected))
        if len(targets) < len(affected):
            return None
        operations: list[PlanPatchOperation] = []
        for session, target in zip(affected, targets):
            session_id = _int_value(session, "id")
            if session_id is None:
                return None
            operations.append(
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session_id,
                    target_date=target.isoformat(),
                    rationale=resolved_change.reason,
                )
            )
        return PlanPatch(
            operations=operations,
            coach_message=_USER_SAFE_PATCH_MESSAGE,
            confirmation_reason="Fenetre large: confirmation requise avant de deplacer plusieurs seances.",
        )

    def _patch_for_change(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        if resolved_change.kind == "move":
            return self._move_patch(resolved_change)
        if resolved_change.kind == "lighten":
            return self._lighten_patch(resolved_change)
        if resolved_change.kind == "replace":
            return self._replace_patch(resolved_change)
        if resolved_change.kind == "swap":
            return self._swap_patch(resolved_change)
        if resolved_change.kind == "create":
            return self._create_patch(resolved_change)
        return None

    def _move_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        target_date = resolved_change.target.date
        if session_id is None or target_date is None:
            return None
        target_session = _single_session_on_date(self._context, target_date.isoformat(), excluding_session_id=session_id)
        if target_session is not None:
            second_session_id = _value(target_session, "id")
            try:
                second_session_id = int(second_session_id)
            except (TypeError, ValueError):
                return None
            return PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="swap_sessions",
                        target_session_id=session_id,
                        second_session_id=second_session_id,
                        rationale=resolved_change.reason,
                    )
                ],
                coach_message=_USER_SAFE_PATCH_MESSAGE,
            )
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="move_session",
                    target_session_id=session_id,
                    target_date=target_date.isoformat(),
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _lighten_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        session_id = resolved_change.source.session_id
        if session_id is None:
            return None
        duration = _light_duration(_session_by_id(self._context, session_id))
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="lighten_day",
                    target_session_id=session_id,
                    new_title="Seance allegee",
                    new_goal="Garder le geste sans accumuler de fatigue.",
                    new_duration_min=duration,
                    new_intensity="easy",
                    new_description="Version facile et raccourcie, sans chercher la performance.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _replace_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        if resolved_change.source.kind == "sport_window":
            return None
        session_id = resolved_change.source.session_id
        if session_id is None:
            return None
        requested = resolved_change.requested_change
        duration = requested.desired_duration_min or _light_duration(_session_by_id(self._context, session_id))
        intensity = _normalized_intensity(requested.desired_intensity) or "easy"
        sport = _normalized_sport_type(requested.desired_sport) or "mobility"
        session_type = "recovery" if requested.desired_sport is None else "easy" if intensity == "easy" else "support"
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="replace_session",
                    target_session_id=session_id,
                    new_title="Seance remplacee",
                    new_goal="Adapter la charge sans perdre la continuite.",
                    new_sport_type=sport,
                    new_session_type=session_type,
                    new_duration_min=duration,
                    new_intensity=intensity,
                    new_description="Remplacement backend borne avant evaluation sportive.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _replace_patches_for_sport_window(self, resolved_change: ResolvedPlanChange) -> dict[str, PlanPatch]:
        source = resolved_change.source
        sport_type = _normalized_sport_type(source.sport_type)
        starts_on = source.starts_on
        ends_on = source.ends_on
        if sport_type is None or starts_on is None or ends_on is None:
            return {}
        patches: dict[str, PlanPatch] = {}
        for session in _scheduled_sessions(self._context):
            session_id = _int_value(session, "id")
            session_date = _session_date(session)
            if session_id is None or session_date is None:
                continue
            if not starts_on <= session_date <= ends_on:
                continue
            if _session_is_completed(session):
                continue
            if _normalized_sport_type(_value(session, "sport_type")) != sport_type:
                continue
            replacement = _replacement_for_unavailable_sport(sport_type)
            duration = _light_duration(session)
            patch = PlanPatch(
                operations=[
                    PlanPatchOperation(
                        operation_type="replace_session",
                        target_session_id=session_id,
                        new_title=replacement["title"],
                        new_goal=replacement["goal"],
                        new_sport_type=replacement["sport_type"],
                        new_session_type=replacement["session_type"],
                        new_duration_min=duration,
                        new_intensity="easy",
                        new_description=replacement["description"],
                        rationale=resolved_change.reason,
                    )
                ],
                coach_message=_USER_SAFE_PATCH_MESSAGE,
            )
            patches[f"backend:replace_unavailable_sport:{session_id}:{sport_type}"] = patch
        return patches

    def _swap_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        source_id = resolved_change.source.session_id
        target_id = resolved_change.target.session_id
        if source_id is None or target_id is None:
            return None
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="swap_sessions",
                    target_session_id=source_id,
                    second_session_id=target_id,
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )

    def _create_patch(self, resolved_change: ResolvedPlanChange) -> PlanPatch | None:
        target_date = resolved_change.target.date
        requested = resolved_change.requested_change
        sport = _normalized_sport_type(requested.desired_sport)
        intensity = _normalized_intensity(requested.desired_intensity) or "easy"
        if target_date is None or sport is None:
            return None
        session_type = "quality" if intensity == "hard" else "easy" if intensity == "easy" else "support"
        return PlanPatch(
            operations=[
                PlanPatchOperation(
                    operation_type="create_session",
                    target_date=target_date.isoformat(),
                    new_title="Seance ajoutee",
                    new_goal="Ajouter une seance bornee depuis une intention structuree.",
                    new_sport_type=sport,
                    new_session_type=session_type,
                    new_duration_min=requested.desired_duration_min or 30,
                    new_intensity=intensity,
                    new_description="Seance creee depuis RequestedPlanChange, avant validation.",
                    rationale=resolved_change.reason,
                )
            ],
            coach_message=_USER_SAFE_PATCH_MESSAGE,
        )


def _candidate_ref(resolved_change: ResolvedPlanChange, patch: PlanPatch) -> str:
    operation = patch.operations[0]
    if operation.operation_type == "move_session":
        return f"backend:move_session:{operation.target_session_id}:{operation.target_date}"
    if operation.operation_type == "swap_sessions":
        return f"backend:swap_sessions:{operation.target_session_id}:{operation.second_session_id}"
    if operation.operation_type == "lighten_day":
        return f"backend:lighten_day:{operation.target_session_id}:easy_{operation.new_duration_min}"
    if operation.operation_type == "replace_session":
        return f"backend:replace_session:{operation.target_session_id}:{operation.new_sport_type}_{operation.new_duration_min}"
    if operation.operation_type == "create_session":
        return f"backend:create_session:{operation.target_date}:{operation.new_sport_type}_{operation.new_duration_min}"
    return f"backend:{resolved_change.kind}:unknown"


def _session_by_id(context: Any, session_id: int) -> Any | None:
    return next((session for session in _scheduled_sessions(context) if _value(session, "id") == session_id), None)


def _single_session_on_date(context: Any, target_date: str, *, excluding_session_id: int) -> Any | None:
    matches = tuple(
        session
        for session in _scheduled_sessions(context)
        if str(_value(session, "scheduled_date") or "")[:10] == target_date
        and _value(session, "id") != excluding_session_id
    )
    return matches[0] if len(matches) == 1 else None


def _scheduled_sessions(context: Any) -> tuple[Any, ...]:
    return tuple(getattr(getattr(context, "plan", None), "scheduled_sessions", ()) or ())


def _session_date(session: Any) -> date | None:
    raw = _value(session, "scheduled_date")
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _session_is_completed(session: Any) -> bool:
    status = str(_value(session, "completion_status") or "").strip().lower()
    return status in {"done", "completed"}


def _affected_training_sessions(context: Any, *, starts_on: date, ends_on: date) -> tuple[Any, ...]:
    affected: list[Any] = []
    for session in sorted(_scheduled_sessions(context), key=lambda item: _session_date(item) or date.max):
        session_date = _session_date(session)
        if session_date is None:
            continue
        if not starts_on <= session_date <= ends_on:
            continue
        if not _is_active_training_session(session):
            continue
        affected.append(session)
    return tuple(affected)


def _open_target_dates_after_window(context: Any, *, starts_after: date, count: int) -> tuple[date, ...]:
    targets: list[date] = []
    for offset in range(1, 11):
        target_date = date.fromordinal(starts_after.toordinal() + offset)
        if _has_active_training_on_date(context, target_date):
            continue
        targets.append(target_date)
        if len(targets) == count:
            break
    return tuple(targets)


def _has_active_training_on_date(context: Any, target_date: date) -> bool:
    return any(
        _is_active_training_session(session) and _session_date(session) == target_date
        for session in _scheduled_sessions(context)
    )


def _is_active_training_session(session: Any) -> bool:
    status = str(_value(session, "completion_status") or "").strip().lower()
    if status in {"done", "completed", "skipped", "canceled", "cancelled"}:
        return False
    sport = str(_value(session, "sport_type") or "").strip().lower()
    session_type = str(_value(session, "session_type") or "").strip().lower()
    return sport not in {"", "rest", "off"} and session_type not in {"rest", "off"}


def _int_value(obj: Any, key: str) -> int | None:
    raw = _value(obj, key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _light_duration(session: Any | None) -> int:
    raw = _value(session, "duration_min") if session is not None else None
    try:
        duration = int(raw or 30)
    except (TypeError, ValueError):
        duration = 30
    return max(15, min(duration, 30))


def _replacement_for_unavailable_sport(sport_type: str) -> dict[str, str]:
    sport = _normalized_sport_type(sport_type) or ""
    if sport in {"running", "cycling"}:
        return {
            "sport_type": "mobility",
            "session_type": "recovery",
            "title": "Mobilite facile",
            "goal": "Garder le mouvement sans utiliser le sport indisponible.",
            "description": "Mobilite douce, gainage leger ou marche facile selon sensations.",
        }
    if sport in {"swimming", "climbing"}:
        return {
            "sport_type": "strength",
            "session_type": "support",
            "title": "Renfo support facile",
            "goal": "Remplacer la seance indisponible par du support controle.",
            "description": "Renforcement general facile, sans chercher la fatigue.",
        }
    return {
        "sport_type": "mobility",
        "session_type": "recovery",
        "title": "Recuperation active",
        "goal": "Retirer la contrainte sportive tout en gardant un signal leger.",
        "description": "Mobilite douce ou marche facile selon sensations.",
    }


def _normalized_intensity(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    aliases = {
        "facile": "easy",
        "easy": "easy",
        "leger": "easy",
        "legere": "easy",
        "light": "easy",
        "modere": "moderate",
        "moderee": "moderate",
        "moderate": "moderate",
        "controle": "moderate",
        "controlee": "moderate",
        "dur": "hard",
        "dure": "hard",
        "hard": "hard",
        "high": "hard",
        "intense": "hard",
        "intensive": "hard",
        "exigeant": "hard",
        "exigeante": "hard",
        "soutenu": "hard",
        "soutenue": "hard",
    }
    return aliases.get(text, text)


def _normalized_sport_type(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    aliases = {
        "bike": "cycling",
        "biking": "cycling",
        "cycle": "cycling",
        "cycling": "cycling",
        "velo": "cycling",
        "vélo": "cycling",
        "natation": "swimming",
        "nage": "swimming",
        "swim": "swimming",
        "swimming": "swimming",
        "course": "running",
        "run": "running",
        "running": "running",
        "renfo": "strength",
        "strength": "strength",
        "mobilite": "mobility",
        "mobilité": "mobility",
        "mobility": "mobility",
    }
    return aliases.get(text, text)


def _value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
