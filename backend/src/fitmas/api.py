from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

load_dotenv(Path(__file__).resolve().parents[4] / ".env")
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fitmas import mutations, repository as repo, schema as s
from fitmas.db import SessionLocal, get_db, init_db
from fitmas.llm import decide, make_plan_summary
from fitmas.models import (
    DayId,
    Extraction,
    Message,
    MessageReply,
    MessageRole,
    Profile,
    TodayView,
    WeeklyPlan,
)
from fitmas.nlp import extract_reply, generate_reply
from fitmas.seed import seed_if_empty

ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_INDEX = ROOT_DIR / "frontend" / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    yield


app = FastAPI(title="FitMAS V0 API", version="0.1.0", lifespan=lifespan)


class IncomingMessage(BaseModel):
    text: str


# ── Static ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(FRONTEND_INDEX)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Read ────────────────────────────────────────────────────────────────────

@app.get("/api/v0/profile", response_model=Profile)
def get_profile(db: Session = Depends(get_db)) -> Profile:
    user = repo.get_user(db)
    return repo.to_pydantic_profile(user)


@app.get("/api/v0/week", response_model=WeeklyPlan)
def get_week(db: Session = Depends(get_db)) -> WeeklyPlan:
    user = repo.get_user(db)
    plan = repo.get_active_plan(db, user.id)
    return repo.to_pydantic_plan(plan)


@app.get("/api/v0/today/{day}", response_model=TodayView)
def get_today(day: DayId, db: Session = Depends(get_db)) -> TodayView:
    user = repo.get_user(db)
    plan = repo.get_active_plan(db, user.id)
    day_row = repo.get_day_plan(db, plan.id, day.value)
    if day_row is None:
        raise HTTPException(status_code=404, detail=f"Day {day.value} not found in plan")
    d = repo.to_pydantic_day(day_row)
    return TodayView(
        day=d.day,
        session_title=d.session_title,
        session_goal=d.session_goal,
        priority=d.priority,
        nutrition_focus=d.nutrition_focus,
        change_notes=d.change_notes,
        watch_items=d.watch_items,
    )


@app.get("/api/v0/messages")
def get_messages(db: Session = Depends(get_db)) -> dict:
    user = repo.get_user(db)
    msgs = repo.get_messages(db, user.id)
    return {"messages": [repo.to_pydantic_message(m).model_dump() for m in msgs]}


# ── Message + mutation loop ──────────────────────────────────────────────────

@app.post("/api/v0/messages", response_model=MessageReply)
def post_message(payload: IncomingMessage, db: Session = Depends(get_db)) -> MessageReply:
    user = repo.get_user(db)
    plan = repo.get_active_plan(db, user.id)

    repo.add_message(db, user.id, "user", payload.text)

    # LLM decision — falls back to rule-based if key missing or error
    pydantic_plan = repo.to_pydantic_plan(plan)
    decision = decide(payload.text, make_plan_summary(pydantic_plan.days))

    if decision:
        mutations.apply(db, plan.id, decision)
        reply_text = decision.fitmas_message
        extraction = Extraction(confidence=0.85)
    else:
        extraction = extract_reply(payload.text)
        fallback = generate_reply(payload.text, extraction)
        reply_text = fallback.assistant_message.text

    repo.add_message(db, user.id, "agent", reply_text)

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
    db.query(s.UserPreference).delete()
    db.query(s.UserConstraint).delete()
    db.query(s.User).delete()
    db.commit()
    from fitmas.seed import seed_if_empty
    seed_if_empty(db)
    return {"status": "reset ok"}
