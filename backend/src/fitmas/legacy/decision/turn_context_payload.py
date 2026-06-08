from __future__ import annotations

from fitmas.legacy.decision.grounding import (
    ReplyGroundingPacket,
    plan_window_facts_from_sessions,
    resolve_temporal_intents,
)


def fact_identity(fact: object) -> str:
    if isinstance(fact, dict):
        return f"{fact.get('category')}:{fact.get('key')}"
    return str(fact)


def build_reply_grounding_packet(
    *,
    user,
    local_date,
    scheduled_sessions,
    turn_plan,
) -> ReplyGroundingPacket:
    temporal_refs = resolve_temporal_intents(
        tuple(getattr(turn_plan, "temporal_references", ()) or ()),
        local_date=local_date,
    )
    return ReplyGroundingPacket(
        local_date=local_date,
        timezone_name=getattr(user, "timezone", None),
        temporal_references=temporal_refs,
        plan_window=plan_window_facts_from_sessions(scheduled_sessions),
    )


def turn_plan_payload(turn_plan) -> dict | None:
    if turn_plan is None:
        return None
    if hasattr(turn_plan, "model_dump"):
        payload = turn_plan.model_dump(mode="json")
    else:
        payload = {
            "primary_intent": getattr(turn_plan, "primary_intent", None),
            "secondary_intents": list(getattr(turn_plan, "secondary_intents", ()) or ()),
        }
    payload["has_plan_mutation"] = bool(getattr(turn_plan, "has_plan_mutation", False))
    return payload
