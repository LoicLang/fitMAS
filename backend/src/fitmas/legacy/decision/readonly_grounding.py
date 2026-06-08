from __future__ import annotations

from typing import Any

from fitmas.legacy.decision import CoachUnderstanding, DecisionExplanation, DecisionOutcome, ReplyContract
from fitmas.legacy.domain.coaching import coach_voice


def answer_outcome_from_understanding(
    understanding: CoachUnderstanding,
    *,
    turn_plan: Any,
) -> DecisionOutcome:
    reason = understanding.user_summary or "Reponse basee sur le contexte disponible."
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    return DecisionOutcome(
        kind="answer",
        commands=(),
        applied_commands=(),
        candidates=(),
        selected_candidate_id=None,
        explanation=DecisionExplanation(
            decision_label=primary_intent or understanding.intent or "answer",
            reason_summary=reason,
            evidence=(),
            tradeoff=None,
            impact={},
            protected=(),
            next_step=None,
        ),
        reply_contract=ReplyContract(
            mode="canonical_readonly_answer",
            audience="user",
            allowed_claims=("read_truth", "answer"),
            forbidden_claims=("mutation_committed", "pending_created", "plan_changed"),
        ),
    )


def grounded_readonly_fallback(
    *,
    understanding: CoachUnderstanding,
    turn_plan: Any,
    grounding_facts: tuple[str, ...],
) -> str | None:
    primary_intent = str(getattr(turn_plan, "primary_intent", "") or "")
    if understanding.intent != "plan_lookup" and primary_intent != "plan_lookup":
        return None
    lines = tuple(_humanize_plan_window_line(line) for line in grounding_facts)
    plan_lines = tuple(line for line in lines if line)
    if not plan_lines:
        return None
    return "Voici ce que j'ai dans le planning : " + " ".join(plan_lines[:8])


def plan_lookup_reply_mentions_plan_truth(text: str, grounding_facts: tuple[str, ...]) -> bool:
    plan_lines = tuple(line for line in grounding_facts if _humanize_plan_window_line(line))
    if not plan_lines:
        return True
    normalized_reply = coach_voice.normalize_for_voice_guard(text)
    for line in plan_lines:
        if _plan_line_has_truth_marker_in_reply(line, normalized_reply):
            return True
    return False


def _humanize_plan_window_line(line: str) -> str | None:
    text = str(line or "").strip()
    if not text.startswith("- ") or " id=" not in text:
        return None
    text = text.removeprefix("- ").strip()
    date_part, _, rest = text.partition(" id=")
    date_part = date_part.strip()
    date_label = _date_label(date_part)
    title = _quoted_title(rest)
    duration = _duration_label(rest)
    if not title:
        title = _sport_label(rest)
    pieces = [date_label, title]
    if duration:
        pieces.append(duration)
    return f"{pieces[0]} : {', '.join(pieces[1:])}."


def _plan_line_has_truth_marker_in_reply(line: str, normalized_reply: str) -> bool:
    date_text = str(line or "").removeprefix("- ").partition(" id=")[0].strip()
    iso_date = date_text.split(" ", 1)[0].strip()
    title = _quoted_title(line)
    for marker in (title, iso_date):
        normalized_marker = coach_voice.normalize_for_voice_guard(str(marker or ""))
        if normalized_marker and normalized_marker in normalized_reply:
            return True
    return False


def _date_label(value: str) -> str:
    text = str(value or "").strip()
    if "(" in text and ")" in text:
        date_text, _, remainder = text.partition("(")
        day_label, _, _ = remainder.partition(")")
        date_text = date_text.strip()
        day_label = day_label.strip()
        if date_text and day_label:
            return f"{day_label} {date_text}"
    return text


def _quoted_title(value: str) -> str | None:
    parts = str(value or "").split('"')
    if len(parts) >= 3:
        title = parts[1].strip()
        if title:
            return title
    return None


def _duration_label(value: str) -> str | None:
    for token in str(value or "").split():
        if token.endswith("min"):
            raw = token.removesuffix("min").strip()
            return f"{raw} min" if raw else None
    return None


def _sport_label(value: str) -> str:
    tokens = str(value or "").split()
    if len(tokens) >= 2:
        return tokens[1]
    return "seance"
