from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Request

from fitmas import schema as s
from fitmas.api_payloads import OnboardPayload, OnboardPreviewPayload
from fitmas.onboarding_contract import build_coach_profile, build_goal_summary
from fitmas.planner import normalize_sports

ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_PUBLIC_DIR = FRONTEND_DIR / "public"
FRONTEND_BUILD_DIR = FRONTEND_DIR / "dist"
FRONTEND_INDEX = FRONTEND_BUILD_DIR / "index.html"


def normalized_onboarding_payload(payload: OnboardPayload | OnboardPreviewPayload) -> dict:
    sports = normalize_sports(payload.sports)
    constraints = normalize_lines(payload.constraints)
    preferences = normalize_lines(payload.preferences)
    normalized = {
        "name": payload.name.strip() or "Loic",
        "primary_objective": payload.primary_objective.strip(),
        "goal_context": payload.goal_context.strip(),
        "sports": sports,
        "weekly_structure_notes": payload.weekly_structure_notes.strip(),
        "current_state_notes": payload.current_state_notes.strip(),
        "constraints": constraints,
        "preferences": preferences,
        "coach_name": (payload.coach_name or "FitMAS").strip() or "FitMAS",
        "coach_preset": payload.coach_preset.strip() or "direct",
        "coach_style": payload.coach_style.strip(),
        "coach_relationship": payload.coach_relationship.strip(),
        "coach_do": payload.coach_do.strip(),
        "coach_dont": payload.coach_dont.strip(),
        "coach_soul": payload.coach_soul.strip(),
        "coach_adjustment_notes": payload.coach_adjustment_notes.strip(),
        "timezone": payload.timezone.strip() or os.getenv("TZ", "Europe/Paris"),
        "telegram_chat_id": payload.telegram_chat_id,
    }
    normalized.update(build_coach_profile(normalized))
    normalized["goal_summary"] = build_goal_summary(normalized)
    return normalized


def normalize_lines(items: list[str]) -> list[str]:
    values: list[str] = []
    for item in items:
        for chunk in re.split(r"[\n;,]+", item):
            clean = chunk.strip(" -•\t")
            if clean:
                values.append(clean)
    return values


def apply_onboarding_to_user(user: s.User, payload: dict) -> None:
    user.name = payload["name"]
    user.objective = payload["primary_objective"]
    user.primary_objective = payload["primary_objective"]
    user.weekly_structure_notes = payload["weekly_structure_notes"]
    user.coaching_style = payload["coach_style"]
    user.coach_name = payload["coach_name"]
    user.coach_style = payload["coach_style"]
    user.coach_relationship = payload["coach_relationship"]
    user.coach_do = payload["coach_do"]
    user.coach_dont = payload["coach_dont"]
    user.coach_soul = payload["coach_soul"]
    user.telegram_chat_id = payload["telegram_chat_id"]
    user.timezone = payload.get("timezone") or user.timezone or os.getenv("TZ", "Europe/Paris")
    user.onboarding_status = "completed"


def build_onboarding_facts(payload: dict) -> list[dict]:
    facts: list[dict] = []

    goal_summary = payload.get("goal_summary") or build_goal_summary(payload)
    if goal_summary:
        facts.append(
            {
                "category": "goal",
                "key": "primary_goal",
                "value": goal_summary,
                "source": "onboarding",
                "confidence": 1.0,
                "confirmed": True,
                "active": True,
            }
        )

    if payload["weekly_structure_notes"]:
        facts.append(
            {
                "category": "availability",
                "key": "weekly_structure",
                "value": payload["weekly_structure_notes"],
                "source": "onboarding",
                "confidence": 1.0,
                "confirmed": True,
                "active": True,
            }
        )

    if payload.get("current_state_notes"):
        facts.append(
            {
                "category": "training_state",
                "key": "current_state",
                "value": payload["current_state_notes"],
                "source": "onboarding",
                "confidence": 0.9,
                "confirmed": True,
                "active": True,
            }
        )

    for index, constraint in enumerate(payload["constraints"]):
        facts.append(
            {
                "category": "constraint",
                "key": f"constraint_{index}",
                "value": constraint,
                "source": "onboarding",
                "confidence": 1.0,
                "confirmed": True,
                "active": True,
            }
        )

    for index, preference in enumerate(payload["preferences"]):
        facts.append(
            {
                "category": "preference",
                "key": f"preference_{index}",
                "value": preference,
                "source": "onboarding",
                "confidence": 1.0,
                "confirmed": True,
                "active": True,
            }
        )

    facts.append(
        {
            "category": "coaching",
            "key": "coach_style_preference",
            "value": (
                f"Coach voulu: preset {payload['coach_preset']} / "
                f"{payload['coach_relationship']} / fait bien: {payload['coach_do']} / "
                f"evite: {payload['coach_dont']}"
            ),
            "source": "onboarding",
            "confidence": 1.0,
            "confirmed": True,
            "active": True,
        }
    )

    return facts


def parse_optional_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def public_base_url(request: Request) -> str:
    explicit = os.getenv("FITMAS_PUBLIC_URL")
    if explicit:
        return explicit.rstrip("/")
    return str(request.base_url).rstrip("/")


def debug_endpoints_enabled() -> bool:
    explicit = os.getenv("FITMAS_ENABLE_DEBUG_ENDPOINTS")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return not bool(os.getenv("FLY_APP_NAME"))


def ensure_debug_enabled() -> None:
    if not debug_endpoints_enabled():
        raise HTTPException(status_code=404, detail="Debug endpoints disabled")
