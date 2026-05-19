from __future__ import annotations

from dataclasses import dataclass

from .base import PromptRender, join_sections, render_json_block


@dataclass(frozen=True, slots=True)
class UnderstandingPromptInput:
    event_summary: str
    context_blocks: tuple[str, ...]


def build_understanding_prompt(data: UnderstandingPromptInput) -> PromptRender:
    system = join_sections(
        "Tu es FitMAS Understanding LLM.",
        "Tu comprends le message utilisateur et le contexte compact.",
        "Tu ne parles pas au user.",
        "Tu ne composes aucun message visible.",
        "Tu ne produis pas de patch planning, ancienne mutation, commande DB ou write.",
        "Tu retournes uniquement un JSON CoachUnderstanding valide.",
    )
    schema = {
        "intent": "close | general_answer | plan_lookup | execution_report | health_signal | availability_signal | plan_change | pending_response | clarification",
        "confidence": "0..1",
        "user_summary": "short factual summary of the user message",
        "extracted_signals": [
            {
                "type": "health | availability | preference | execution | readiness | planning | pending | other",
                "label": "short typed label",
                "status": "new | update | correction",
                "severity": "low | medium | high | unknown",
                "confidence": "0..1",
                "evidence": "user-provided evidence only",
                "payload": {
                    "action_type": "record_health_signal | record_availability | record_preference | record_execution_update | null",
                    "health_signal": "health signal label when action_type=record_health_signal",
                    "body_area": "body area or null",
                    "availability": "available | unavailable | limited | unknown",
                    "window_text": "availability window in user words",
                    "sport_type": "running | cycling | swimming | strength | null",
                    "scope": "sport | day | week | general | time | location | null",
                    "starts_on": "YYYY-MM-DD or null",
                    "ends_on": "YYYY-MM-DD or null",
                    "preference": "preference text when action_type=record_preference",
                    "polarity": "prefer | avoid",
                    "target_ref": "typed execution target reference or null",
                    "target_session_id": "integer id or null",
                    "completed": "true | false | null",
                    "status": "completed | not_completed | unknown",
                },
            }
        ],
        "requested_change": {
            "kind": "move | swap | lighten | replace | create | constraint_window | remove_optional | unknown",
            "source_ref": "typed reference or null",
            "target_ref": "typed reference or null",
            "desired_sport": "sport or null",
            "desired_duration_min": "integer or null",
            "desired_intensity": "string or null",
            "reason": "why the change is requested",
            "risk_signals": ["fatigue | pain | load | availability"],
        },
        "pending_resolution": {
            "type": "accept_pending | reject_pending | modify_pending | ignore | needs_clarification",
            "reason": "why this pending interpretation fits",
        },
        "clarification_need": {
            "question": "only if essential information is missing",
            "missing_fields": ["field names"],
        },
    }
    prompt = join_sections(
        f"InputEvent:\n{data.event_summary}",
        "CoachContext compact:",
        *data.context_blocks,
        "Output JSON schema:",
        render_json_block(schema),
    )
    return PromptRender(system=system, prompt=prompt, max_tokens=900)
