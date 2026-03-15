from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from fitmas.models import DayId, MessageReply, Profile, TodayView, WeeklyPlan
from fitmas.nlp import extract_reply, generate_reply
from fitmas.state import build_messages, build_profile, build_week_plan


app = FastAPI(title="FitMAS V0 API", version="0.1.0")

PROFILE = build_profile()
PLAN = build_week_plan()
MESSAGES = build_messages()
ROOT_DIR = Path(__file__).resolve().parents[3]
FRONTEND_INDEX = ROOT_DIR / "frontend" / "index.html"


class IncomingMessage(BaseModel):
    text: str


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(FRONTEND_INDEX)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v0/profile", response_model=Profile)
def get_profile() -> Profile:
    return PROFILE


@app.get("/api/v0/week", response_model=WeeklyPlan)
def get_week() -> WeeklyPlan:
    return PLAN


@app.get("/api/v0/today/{day}", response_model=TodayView)
def get_today(day: DayId) -> TodayView:
    selected = next(item for item in PLAN.days if item.day == day)
    return TodayView(
        day=selected.day,
        session_title=selected.session_title,
        session_goal=selected.session_goal,
        priority=selected.priority,
        nutrition_focus=selected.nutrition_focus,
        change_notes=selected.change_notes,
        watch_items=selected.watch_items,
    )


@app.get("/api/v0/messages")
def get_messages() -> dict[str, list[dict[str, str]]]:
    return {"messages": [message.model_dump() for message in MESSAGES]}


@app.post("/api/v0/messages", response_model=MessageReply)
def post_message(payload: IncomingMessage) -> MessageReply:
    extraction = extract_reply(payload.text)
    reply = generate_reply(payload.text, extraction)
    MESSAGES.append(reply.user_message)
    MESSAGES.append(reply.assistant_message)
    return reply
