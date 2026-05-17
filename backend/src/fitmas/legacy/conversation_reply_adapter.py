from __future__ import annotations

from fitmas import final_reply


FinalReplyContext = final_reply.FinalReplyContext
BlockedEvent = final_reply.BlockedEvent


def build_plan_adaptation_reply_context(*args, **kwargs):
    return final_reply.build_plan_adaptation_reply_context(*args, **kwargs)


def close_turn_outage_fallback_reply(*args, **kwargs):
    return final_reply.close_turn_outage_fallback_reply(*args, **kwargs)


def compose_close_turn_reply(*args, **kwargs):
    return final_reply.compose_close_turn_reply(*args, **kwargs)


def compose_execution_report_reply(*args, **kwargs):
    return final_reply.compose_execution_report_reply(*args, **kwargs)


def compose_final_reply(*args, **kwargs):
    return final_reply.compose_final_reply(*args, **kwargs)


def compose_no_change_reply(*args, **kwargs):
    return final_reply.compose_no_change_reply(*args, **kwargs)


def compose_plan_adaptation_reply(*args, **kwargs):
    return final_reply.compose_plan_adaptation_reply(*args, **kwargs)


def compose_plan_lookup_reply(*args, **kwargs):
    return final_reply.compose_plan_lookup_reply(*args, **kwargs)


def outage_fallback_reply(*args, **kwargs):
    return final_reply.outage_fallback_reply(*args, **kwargs)


def request_text(*args, **kwargs):
    return final_reply.request_text(*args, **kwargs)


def verify_factual_reply(*args, **kwargs):
    return final_reply.verify_factual_reply(*args, **kwargs)


def verify_post_event_reply(*args, **kwargs):
    return final_reply.verify_post_event_reply(*args, **kwargs)


def verify_uncommitted_reply(*args, **kwargs):
    return final_reply.verify_uncommitted_reply(*args, **kwargs)
