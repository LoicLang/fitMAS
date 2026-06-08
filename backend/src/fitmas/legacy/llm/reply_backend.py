from __future__ import annotations

import os

from fitmas.legacy.llm.gateway import request_text
from fitmas.legacy.llm.prompts.reply import ReplyPromptBlockedEvent, ReplyPromptInput, build_reply_prompt

from .reply_types import BlockedEvent, FinalReplyContext, RequestTextFn
from .reply_event_verifier import close_turn_outage_fallback_reply, outage_fallback_reply
from .reply_factual_verifier import verify_factual_reply
from .reply_validation import is_valid_final_reply, is_valid_plan_lookup_reply
from .reply_verifiers import (
    build_close_turn_reply_verifier_prompt,
    build_factual_reply_verifier_prompt,
    build_post_event_reply_verifier_prompt,
    build_uncommitted_reply_verifier_prompt,
    is_valid_close_turn_reply,
    verify_post_event_reply,
    verify_uncommitted_reply,
)


def build_final_reply_prompt(context: FinalReplyContext) -> tuple[str, str]:
    """Build the repair/composition prompt from machine facts only."""
    rendered = build_reply_prompt(
        ReplyPromptInput(
            pipeline=context.pipeline,
            capability=context.pipeline_capability,
            user_text=context.user_text,
            original_llm_reply=context.original_llm_reply,
            committed_events=context.committed_events,
            blocked_events=tuple(
                ReplyPromptBlockedEvent(
                    command=event.command,
                    reason=event.reason,
                    suggested_fix=event.suggested_fix,
                    warning=event.warning,
                )
                for event in context.blocked_events
            ),
            pending_summary=context.pending_summary,
            memory_actions_applied=context.memory_actions_applied,
            execution_actions_applied=context.execution_actions_applied,
            allowed_to_claim_mutation=context.allowed_to_claim_mutation,
            extra_facts=context.extra_facts,
        )
    )
    return rendered.system, rendered.prompt


def compose_final_reply(
    context: FinalReplyContext,
    *,
    request_text_fn: RequestTextFn = request_text,
    force: bool = False,
) -> str | None:
    if not force and request_text_fn is request_text and os.getenv("FITMAS_ENABLE_FINAL_REPLY_COMPOSER") == "0":
        return None
    system, prompt = build_final_reply_prompt(context)
    reply = request_text_fn(system=system, prompt=prompt, max_tokens=300)
    if not is_valid_final_reply(reply, context):
        return None
    return str(reply).strip()


from fitmas.legacy.llm.reply_conversation import (  # noqa: E402
    compose_execution_report_reply,
    compose_no_change_reply,
    compose_plan_lookup_reply,
)
from fitmas.legacy.llm.reply_plan_adaptation import (  # noqa: E402
    build_plan_adaptation_reply_context,
    compose_plan_adaptation_reply,
)
from fitmas.legacy.llm.reply_close_turn import compose_close_turn_reply  # noqa: E402
