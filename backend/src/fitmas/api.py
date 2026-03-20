from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fitmas.activities import infer_activity_title, match_activity_to_day, normalize_activity_sport
from fitmas import mutations, repository as repo, schema as s
from fitmas.db import SessionLocal, get_db, init_db
from fitmas.llm import (
    decide,
    extract_facts,
    formulate_onboarding_recap,
    formulate_week_plan,
    make_plan_summary,
    preview_coach_voice,
    select_prompt_facts,
)
from fitmas.models import (
    Activity,
    DayId,
    Extraction,
    Message,
    MessageReply,
    MessageRole,
    OnboardPreview,
    OnboardResult,
    Profile,
    TodayView,
    UserFact,
    WeeklyPlan,
)
from fitmas.nlp import extract_reply, generate_reply
from fitmas.planner import build_week_plan, normalize_sports
from fitmas.seed import seed_if_empty
from fitmas import strava
from fitmas.time_context import build_time_context

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    logger.info("FitMAS API ready")
    yield


app = FastAPI(title="FitMAS V0 API", version="0.1.0", lifespan=lifespan)


class IncomingMessage(BaseModel):
    text: str


class OnboardPayload(BaseModel):
    name: str
    primary_objective: str
    sports: list[str]
    weekly_structure_notes: str
    constraints: list[str]
    preferences: list[str]
    coach_name: str | None = None
    coach_style: str
    coach_relationship: str
    coach_do: str
    coach_dont: str
    coach_soul: str
    telegram_chat_id: int | None = None


class OnboardPreviewPayload(OnboardPayload):
    pass


class ManualActivityPayload(BaseModel):
    sport_type: str
    title: str | None = None
    duration_min: int | None = None
    distance_m: float | None = None
    elevation_m: float | None = None
    perceived_load: int | None = None
    note: str = ""
    started_at: str | None = None


# ── Static ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(FRONTEND_INDEX)


@app.get("/manifest.json", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "manifest.json")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _send_telegram_message(*, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return False
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    return bool(payload.get("ok"))


# ── Read ────────────────────────────────────────────────────────────────────

@app.get("/api/v0/profile", response_model=Profile)
def get_profile(db: Session = Depends(get_db)) -> Profile:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    return repo.to_pydantic_profile(user)


@app.get("/api/v0/week", response_model=WeeklyPlan)
def get_week(db: Session = Depends(get_db)) -> WeeklyPlan:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    plan = repo.get_active_plan(db, user.id)
    return repo.to_pydantic_plan(plan)


@app.get("/api/v0/today/{day}", response_model=TodayView)
def get_today(day: DayId, db: Session = Depends(get_db)) -> TodayView:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    plan = repo.get_active_plan(db, user.id)
    day_row = repo.get_day_plan(db, plan.id, day.value)
    if day_row is None:
        raise HTTPException(status_code=404, detail=f"Day {day.value} not found in plan")
    d = repo.to_pydantic_day(day_row)
    return TodayView(
        day=d.day,
        sport_type=d.sport_type,
        session_type=d.session_type,
        session_title=d.session_title,
        session_goal=d.session_goal,
        duration_min=d.duration_min,
        intensity=d.intensity,
        priority=d.priority,
        nutrition_focus=d.nutrition_focus,
        change_notes=d.change_notes,
        watch_items=d.watch_items,
    )


@app.get("/api/v0/messages")
def get_messages(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        return {"messages": []}
    msgs = repo.get_messages(db, user.id)
    return {"messages": [repo.to_pydantic_message(m).model_dump() for m in msgs]}


@app.get("/api/v0/facts", response_model=list[UserFact])
def get_facts(db: Session = Depends(get_db)) -> list[UserFact]:
    user = repo.get_user_optional(db)
    if user is None:
        return []
    facts = repo.get_active_facts(db, user.id)
    return [repo.to_pydantic_fact(fact) for fact in facts]


@app.get("/api/v0/activities", response_model=list[Activity])
def get_activities(db: Session = Depends(get_db)) -> list[Activity]:
    user = repo.get_user_optional(db)
    if user is None:
        return []
    activities = repo.get_activities(db, user.id)
    return [repo.to_pydantic_activity(activity) for activity in activities]


@app.get("/api/v0/strava/status")
def get_strava_status(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        return {"configured": strava.is_configured(), "connected": False, "last_sync_at": None}
    connection = repo.get_strava_connection(db, user.id)
    return {
        "configured": strava.is_configured(),
        "connected": connection is not None,
        "last_sync_at": connection.last_sync_at.isoformat() if connection and connection.last_sync_at else None,
        "scopes": connection.scopes if connection else "",
    }


@app.post("/api/v0/debug/heartbeat/{kind}")
def trigger_debug_heartbeat(kind: str, send: bool = True, db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    from fitmas.heartbeat import morning_briefing, pre_session_reminder

    handlers = {
        "morning": morning_briefing,
        "pre_session": pre_session_reminder,
    }
    handler = handlers.get(kind)
    if handler is None:
        raise HTTPException(status_code=400, detail="Unsupported heartbeat kind")

    text = handler()
    if not text:
        return {
            "kind": kind,
            "triggered": False,
            "sent": False,
            "reason": "no_op",
        }

    sent = False
    delivery_error = None
    if send:
        if not user.telegram_chat_id:
            delivery_error = "missing_telegram_chat_id"
        else:
            try:
                sent = _send_telegram_message(chat_id=user.telegram_chat_id, text=text)
            except Exception as exc:
                logger.exception("Failed to send debug heartbeat to Telegram")
                delivery_error = str(exc)

    return {
        "kind": kind,
        "triggered": True,
        "sent": sent,
        "delivery_error": delivery_error,
        "message": text,
    }


@app.get("/api/v0/strava/auth")
def start_strava_auth(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    if not strava.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")
    callback_url = _public_base_url(request) + "/api/v0/strava/callback"
    url = strava.build_auth_url(callback_url=callback_url, state=str(user.id))
    return RedirectResponse(url=url, status_code=302)


@app.get("/api/v0/strava/callback")
def finish_strava_auth(code: str, state: str, db: Session = Depends(get_db)) -> dict:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    if str(user.id) != state:
        raise HTTPException(status_code=400, detail="Invalid Strava state")
    if not strava.is_configured():
        raise HTTPException(status_code=503, detail="Strava is not configured")

    token_payload = strava.exchange_code_for_token(code=code)
    connection = strava.store_connection_from_token_payload(db, user_id=user.id, payload=token_payload)
    plan = repo.get_active_plan(db, user.id)
    week_days = repo.to_pydantic_plan(plan).days
    imported = strava.import_recent_activities(db, user_id=user.id, connection=connection, week_days=week_days, plan_id=plan.id, plan_created_at=plan.created_at)
    return {
        "connected": True,
        "imported": imported,
        "athlete_id": connection.athlete_id,
        "last_sync_at": connection.last_sync_at.isoformat() if connection.last_sync_at else None,
    }


@app.post("/api/v0/activities/manual", response_model=Activity)
def create_manual_activity(payload: ManualActivityPayload, db: Session = Depends(get_db)) -> Activity:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    sport_type = normalize_activity_sport(payload.sport_type)
    title = (payload.title or "").strip() or infer_activity_title(sport_type, payload.duration_min, payload.note)
    started_at = _parse_optional_datetime(payload.started_at)
    plan = repo.get_active_plan(db, user.id)
    week_days = repo.to_pydantic_plan(plan).days
    matched_day, match_reason = match_activity_to_day(
        sport_type=sport_type,
        started_at=started_at,
        duration_min=payload.duration_min,
        week_days=week_days,
    )

    activity = repo.add_activity(
        db,
        user_id=user.id,
        source="manual",
        sport_type=sport_type,
        title=title,
        duration_min=payload.duration_min,
        distance_m=payload.distance_m,
        elevation_m=payload.elevation_m,
        perceived_load=payload.perceived_load,
        note=payload.note.strip(),
        started_at=started_at,
        matched_day=matched_day,
        match_reason=match_reason,
    )

    # Mark matched day as done
    if matched_day:
        repo.mark_day_completed(db, plan.id, matched_day)
        logger.info("Marked %s as done (manual activity: %s)", matched_day, title)

    return repo.to_pydantic_activity(activity)


@app.post("/api/v0/onboard/preview", response_model=OnboardPreview)
def preview_onboarding(payload: OnboardPreviewPayload) -> OnboardPreview:
    normalized_payload = _normalized_onboarding_payload(payload)
    time_context = build_time_context(normalized_payload.get("timezone"))
    recap = formulate_onboarding_recap(normalized_payload, time_context=time_context)
    preview = preview_coach_voice(normalized_payload, time_context=time_context)
    return OnboardPreview(
        normalized_sports=normalized_payload["sports"],
        coach_preview=preview,
        recap=recap,
    )


@app.post("/api/v0/onboard", response_model=OnboardResult)
def onboard(payload: OnboardPayload, db: Session = Depends(get_db)) -> OnboardResult:
    normalized_payload = _normalized_onboarding_payload(payload)
    time_context = build_time_context(normalized_payload.get("timezone"))
    recap = formulate_onboarding_recap(normalized_payload, time_context=time_context)
    planner_output = build_week_plan(
        sports=normalized_payload["sports"],
        weekly_structure_notes=normalized_payload["weekly_structure_notes"],
        constraints=normalized_payload["constraints"],
        coach_name=normalized_payload["coach_name"],
    )
    enriched_week = formulate_week_plan(
        planner_output,
        user_profile=normalized_payload,
        coach_profile=normalized_payload,
        time_context=time_context,
    )

    user = repo.get_user_optional(db)
    if user is None:
        user = s.User(name=normalized_payload["name"])
        db.add(user)
        db.flush()

    _apply_onboarding_to_user(user, normalized_payload)
    db.commit()

    repo.replace_user_lists(
        db,
        user,
        sports=normalized_payload["sports"],
        constraints=normalized_payload["constraints"],
        preferences=normalized_payload["preferences"],
    )
    repo.replace_user_facts(db, user.id, _build_onboarding_facts(normalized_payload))

    db.query(s.CoachMessage).filter(s.CoachMessage.user_id == user.id).delete()
    db.commit()

    repo.add_message(
        db,
        user.id,
        "agent",
        f"{normalized_payload['coach_name']} est en place. Je t'ai pose une premiere semaine qu'on pourra faire bouger intelligemment.",
    )

    plan = repo.replace_plan(
        db,
        user.id,
        intention=enriched_week["intention"],
        summary=enriched_week["summary"],
        days=[dict(day) for day in enriched_week["days"]],
    )

    return OnboardResult(
        recap=recap,
        week_plan=repo.to_pydantic_plan(plan),
    )


@app.post("/api/v0/week/regenerate", response_model=WeeklyPlan)
def regenerate_week(db: Session = Depends(get_db)) -> WeeklyPlan:
    """Generate a fresh weekly plan based on current profile."""
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")

    sports = [sport.sport_type for sport in user.sports if sport.active]
    constraints = [c.text for c in user.constraints]
    coach_profile = {
        "coach_name": user.coach_name,
        "coach_style": user.coach_style,
        "coach_relationship": user.coach_relationship,
        "coach_do": user.coach_do,
        "coach_dont": user.coach_dont,
        "coach_soul": user.coach_soul,
    }
    user_profile = {
        "primary_objective": user.primary_objective,
        "sports": sports,
        "weekly_structure_notes": user.weekly_structure_notes,
        "constraints": constraints,
        "preferences": [p.text for p in user.preferences],
        "timezone": user.timezone,
        **coach_profile,
    }

    planner_output = build_week_plan(
        sports=sports,
        weekly_structure_notes=user.weekly_structure_notes,
        constraints=constraints,
        coach_name=user.coach_name,
    )
    enriched_week = formulate_week_plan(
        planner_output,
        user_profile=user_profile,
        coach_profile=user_profile,
        time_context=build_time_context(user.timezone),
    )

    plan = repo.replace_plan(
        db,
        user.id,
        intention=enriched_week["intention"],
        summary=enriched_week["summary"],
        days=[dict(day) for day in enriched_week["days"]],
    )

    repo.add_message(
        db, user.id, "agent",
        f"Nouvelle semaine posee. {enriched_week['intention']}",
    )
    logger.info("Week regenerated for user %s", user.id)
    return repo.to_pydantic_plan(plan)


@app.post("/api/v0/strava/sync")
def sync_strava(db: Session = Depends(get_db)) -> dict:
    """Trigger a Strava sync — pull recent activities and mark matched days as done."""
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    if not strava.is_configured():
        return {"synced": False, "reason": "Strava not configured"}
    connection = repo.get_strava_connection(db, user.id)
    if connection is None:
        return {"synced": False, "reason": "Strava not connected"}
    plan = repo.get_active_plan(db, user.id)
    week_days = repo.to_pydantic_plan(plan).days
    imported = strava.import_recent_activities(
        db, user_id=user.id, connection=connection, week_days=week_days, plan_id=plan.id, plan_created_at=plan.created_at,
    )
    logger.info("Strava sync: %d new activities imported", imported)
    return {"synced": True, "imported": imported}


# ── Message + mutation loop ──────────────────────────────────────────────────

@app.post("/api/v0/messages", response_model=MessageReply)
def post_message(payload: IncomingMessage, db: Session = Depends(get_db)) -> MessageReply:
    user = repo.get_user_optional(db)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded user yet")
    plan = repo.get_active_plan(db, user.id)

    repo.add_message(db, user.id, "user", payload.text)
    logger.info("User message: %s", payload.text[:120])

    # Build conversation history for LLM context
    msgs = repo.get_messages(db, user.id)
    conversation_history = [{"role": m.role, "text": m.text} for m in msgs]
    active_facts = [repo.to_pydantic_fact(fact).model_dump() for fact in repo.get_active_facts(db, user.id)]

    # LLM decision — falls back to rule-based if key missing or error
    pydantic_plan = repo.to_pydantic_plan(plan)
    decision = decide(
        payload.text,
        make_plan_summary(pydantic_plan.days),
        conversation_history=conversation_history,
        coach_context={
            "coach_name": user.coach_name,
            "coach_style": user.coach_style,
            "coach_relationship": user.coach_relationship,
            "coach_do": user.coach_do,
            "coach_dont": user.coach_dont,
            "coach_soul": user.coach_soul,
            "timezone": user.timezone,
            "selected_facts": select_prompt_facts(active_facts),
        },
        remembered_facts=active_facts,
        time_context=build_time_context(user.timezone),
    )

    if decision:
        mutations.apply(db, plan.id, decision)
        reply_text = decision.fitmas_message
        extraction = Extraction(confidence=0.85)
        logger.info("LLM reply (%s): %s", decision.mutation_type, reply_text[:120])
    else:
        extraction = extract_reply(payload.text)
        fallback = generate_reply(payload.text, extraction)
        reply_text = fallback.assistant_message.text
        logger.info("Fallback reply: %s", reply_text[:120])

    repo.add_message(db, user.id, "agent", reply_text)
    extracted_facts = extract_facts(payload.text, reply_text, active_facts)
    if extracted_facts:
        repo.upsert_facts(db, user.id, extracted_facts)

    return MessageReply(
        user_message=Message(role=MessageRole.USER, text=payload.text),
        extraction=extraction,
        assistant_message=Message(role=MessageRole.AGENT, text=reply_text),
    )


# ── Admin ────────────────────────────────────────────────────────────────────

@app.post("/api/v0/reset")
def reset(db: Session = Depends(get_db)) -> dict[str, str]:
    """Wipe all data and re-seed. Use at the start of each new week."""
    db.query(s.WatchItem).delete()
    db.query(s.ChangeNote).delete()
    db.query(s.DayPlan).delete()
    db.query(s.WeeklyPlan).delete()
    db.query(s.CoachMessage).delete()
    db.query(s.Activity).delete()
    db.query(s.UserFact).delete()
    db.query(s.UserSport).delete()
    db.query(s.UserPreference).delete()
    db.query(s.UserConstraint).delete()
    db.query(s.User).delete()
    db.commit()
    return {"status": "reset ok"}


def _normalized_onboarding_payload(payload: OnboardPayload | OnboardPreviewPayload) -> dict:
    coach_name = (payload.coach_name or "FitMAS").strip() or "FitMAS"
    sports = normalize_sports(payload.sports)
    constraints = _normalize_lines(payload.constraints)
    preferences = _normalize_lines(payload.preferences)
    return {
        "name": payload.name.strip() or "Loic",
        "primary_objective": payload.primary_objective.strip(),
        "sports": sports,
        "weekly_structure_notes": payload.weekly_structure_notes.strip(),
        "constraints": constraints,
        "preferences": preferences,
        "coach_name": coach_name,
        "coach_style": payload.coach_style.strip() or "direct",
        "coach_relationship": payload.coach_relationship.strip(),
        "coach_do": payload.coach_do.strip(),
        "coach_dont": payload.coach_dont.strip(),
        "coach_soul": payload.coach_soul.strip(),
        "timezone": os.getenv("TZ", "Europe/Paris"),
        "telegram_chat_id": payload.telegram_chat_id,
    }


def _normalize_lines(items: list[str]) -> list[str]:
    values: list[str] = []
    for item in items:
        for chunk in item.split("\n"):
            clean = chunk.strip(" -•\t")
            if clean:
                values.append(clean)
    return values


def _apply_onboarding_to_user(user: s.User, payload: dict) -> None:
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


def _build_onboarding_facts(payload: dict) -> list[dict]:
    facts: list[dict] = []

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
            "value": f"Coach voulu: {payload['coach_style']} / {payload['coach_relationship']}",
            "source": "onboarding",
            "confidence": 1.0,
            "confirmed": True,
            "active": True,
        }
    )

    return facts


def _parse_optional_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _public_base_url(request: Request) -> str:
    explicit = os.getenv("FITMAS_PUBLIC_URL")
    if explicit:
        return explicit.rstrip("/")
    return str(request.base_url).rstrip("/")
