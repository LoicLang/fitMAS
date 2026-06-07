"""Couche-2 probe for Slice 3a: does the coach call propose_week and show a coherent week?

Self-contained: builds an in-memory WorldSnapshot with last-week real training, then
drives CoachAgent -> policy -> reply -> guard with a real provider (coach @1024,
generation @4096, reply @1024). No DB. Sends "fais-moi ma semaine prochaine" and prints
the structured decision + reply, so we can judge whether the coach triggers the engine,
grounds a sensible seed, and the reply is honest (no false write claim).

Run:
    set -a && . ./.env && set +a
    .venv/bin/python scripts/v0_eval/probe_propose_week.py --provider deepseek
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fitmas.runtime_v0.agent import CoachAgent  # noqa: E402
from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.policy import RuntimePolicy  # noqa: E402
from fitmas.runtime_v0.prompts.coach_system import COACH_SYSTEM_PROMPT  # noqa: E402
from fitmas.runtime_v0.prompts.reply_system import REPLY_SYSTEM_PROMPT  # noqa: E402
from fitmas.runtime_v0.guard import OutputGuard  # noqa: E402
from fitmas.runtime_v0.reply import ReplyComposer  # noqa: E402
from fitmas.runtime_v0.result import build_runtime_result  # noqa: E402
from fitmas.runtime_v0.snapshot import ActivityView, SessionView, WorldSnapshot  # noqa: E402
from fitmas.runtime_v0.state import ConversationState  # noqa: E402
from fitmas.runtime_v0.tool_catalog import for_event  # noqa: E402
from fitmas.runtime_v0.tools_read import ToolContext  # noqa: E402

from scripts.v0_eval.provider_clients import (  # noqa: E402
    MeteredLLMClient,
    ProviderConfigError,
    build_provider_client,
)


def _snapshot(today: date, now: datetime) -> WorldSnapshot:
    # Last week (real, done): a threshold key + easy footings + a long run.
    last = [
        SessionView(id=1, date=today - timedelta(days=6), sport="run", title="Footing", duration_min=45, intensity_label="easy", priority="optional", status="done"),
        SessionView(id=2, date=today - timedelta(days=4), sport="run", title="Seuil 3x8", duration_min=60, intensity_label="hard", priority="key", status="done"),
        SessionView(id=3, date=today - timedelta(days=2), sport="run", title="Footing", duration_min=50, intensity_label="easy", priority="secondary", status="done"),
        SessionView(id=4, date=today - timedelta(days=1), sport="run", title="Sortie longue", duration_min=90, intensity_label="moderate", priority="key", status="done"),
    ]
    activities = [
        ActivityView(id=10, date=today - timedelta(days=6), sport="run", duration_min=45, distance_km=8.0, notes=None, source="strava"),
        ActivityView(id=11, date=today - timedelta(days=4), sport="run", duration_min=60, distance_km=12.0, notes="seuil", source="strava"),
        ActivityView(id=12, date=today - timedelta(days=1), sport="run", duration_min=90, distance_km=18.0, notes="longue", source="strava"),
    ]
    return WorldSnapshot(
        user_id=1, today=today, now=now, timezone="Europe/Paris", objective="10 km sous 40 min",
        current_plan=(), recent_plan=tuple(last), recent_activities=tuple(activities),
        active_facts=(), active_pending=None, recent_execution_events=(), recent_plan_events=(),
        conversation_state=ConversationState(None, None, None, None, None),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Couche-2 probe for propose_week (Slice 3a)")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--message", default="fais-moi ma semaine prochaine")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()

    try:
        coach = build_provider_client(args.provider, max_tokens=1024)
        generation = build_provider_client(args.provider, max_tokens=4096)
        # Reply needs >1024 too: rendering a whole week as prose with a reasoning model
        # (deepseek-v4-pro) truncates at 1024 (the week dump cuts off). 4096 renders a
        # clean, honest coach message. Caller-config note for the Slice 4 runtime wiring.
        reply = build_provider_client(args.provider, max_tokens=4096)
    except ProviderConfigError as exc:
        print(f"provider_config_error: {exc}\nHint: set -a && . ./.env && set +a")
        return 2

    model = getattr(getattr(coach, "profile", None), "model", "unknown")
    coach_m = MeteredLLMClient(coach, provider=args.provider, model=model)
    generation_m = MeteredLLMClient(generation, provider=args.provider, model=model)
    reply_m = MeteredLLMClient(reply, provider=args.provider, model=model)

    now = datetime(2026, 6, 7, 18, 0, tzinfo=timezone.utc)  # a Sunday evening
    snapshot = _snapshot(now.date(), now)
    ctx = ToolContext(db_path=None, snapshot=snapshot, generation_llm=generation_m)
    event = InputEvent(id="probe-1", user_id=1, source="telegram", type="user_message", text=args.message, payload={}, occurred_at=now)

    proposal = CoachAgent(coach_m, COACH_SYSTEM_PROMPT).run(
        event, snapshot.header(), for_event(event, snapshot), max_steps=args.max_steps, tool_context=ctx
    )
    policy = RuntimePolicy().evaluate(proposal, snapshot)
    result = build_runtime_result(event, "probe-1", proposal, policy, ())
    composed = ReplyComposer(reply_m, REPLY_SYSTEM_PROMPT).compose(result, snapshot)
    guard = OutputGuard(snapshot.today).verify(composed, result)

    print("=" * 80)
    print(f"PROBE propose_week  |  {args.provider}/{model}  |  today={snapshot.today}")
    print(f"USER: {args.message}")
    print(f"  last-week training: {sum(s.duration_min for s in snapshot.recent_plan)} min over {len(snapshot.recent_plan)} sessions (key: Seuil 3x8)")
    print("-" * 80)
    tools_called = [c.get("name") for c in proposal.tool_trace]
    print(f"  tools called by coach: {tools_called or '(none)'}")
    print(f"  proposal.type = {proposal.type}")
    if proposal.week_proposal is not None:
        wp = proposal.week_proposal
        print(f"  WEEK PROPOSAL: source={wp.source} start={wp.week_start} load={wp.week_load} band={wp.band} key={wp.key_type}")
        for s in wp.sessions:
            print(f"    {s['date']} {s['type']:12} {s['duration_min']:3}min {s['intensity']}")
    print(f"  policy.action = {policy.action}  commands = {len(policy.commands)}")
    print(f"  guard.ok = {guard.ok}  reasons = {guard.blocked_reasons}")
    print(f"  REPLY: {composed}")
    print(f"  cost: coach_in={coach_m.tokens_in} coach_out={coach_m.tokens_out} gen_out={generation_m.tokens_out}")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
