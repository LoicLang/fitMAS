from __future__ import annotations

from enum import Enum


class IntentCategory(str, Enum):
    CASUAL_CHAT = "casual_chat"
    CLOSE_TURN = "close_turn"
    EXECUTION_REPORT = "execution_report"
    HEALTH_SIGNAL = "health_signal"
    PLAN_NEGOTIATION = "plan_negotiation"
    PLAN_LOOKUP = "plan_lookup"
    ACTIVITY_REVIEW = "activity_review"
    ACTIVITY_HIGHLIGHTS = "activity_highlights"
    LOAD_REVIEW = "load_review"
    FACT_RECALL = "fact_recall"
    GENERIC_QUESTION = "generic_question"
