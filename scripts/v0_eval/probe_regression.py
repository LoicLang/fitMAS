"""Couche-2 regression probe: did teaching the coach propose_week (+ recent_training
in the header) break the OTHER intents? Runs key scenarios through the full handle_event
with a real provider and checks the proposal type — especially that propose_week does NOT
over-trigger on indispo / move / execution / resolution turns.

Run:
    set -a && . ./.env && set +a
    .venv/bin/python scripts/v0_eval/probe_regression.py --provider deepseek
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event  # noqa: E402

from scripts.v0_eval.provider_clients import (  # noqa: E402
    MeteredLLMClient,
    ProviderConfigError,
    build_provider_client,
)
from scripts.v0_eval.scenarios import scenario_by_name, seed_db  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")

# (scenario name OR custom, expected proposal type, whether propose_week is allowed)
EXISTING = [
    ("current_plan", "answer"),
    ("skipped_yesterday", "execution_update"),
    ("explicit_lighten", "plan_patch"),
    ("key_session_pending", "plan_patch"),
    ("health_resolution", "fact_resolution"),
    ("move_today_open_week", "ask_clarification|plan_patch"),
]


def _indispo_3_jours() -> tuple[dict, InputEvent]:
    state = {
        "today": "2026-06-01",
        "sessions": [
            {"id": 81, "date": "2026-06-01", "sport": "run", "title": "Footing", "duration_min": 40, "intensity_label": "easy", "priority": "secondary", "status": "planned"},
            {"id": 82, "date": "2026-06-02", "sport": "run", "title": "VMA courte", "duration_min": 45, "intensity_label": "hard", "priority": "key", "status": "planned"},
            {"id": 83, "date": "2026-06-03", "sport": "run", "title": "Footing récup", "duration_min": 35, "intensity_label": "easy", "priority": "secondary", "status": "planned"},
            {"id": 84, "date": "2026-06-05", "sport": "run", "title": "Sortie longue", "duration_min": 80, "intensity_label": "moderate", "priority": "key", "status": "planned"},
        ],
    }
    event = InputEvent(
        id="evt-indispo3", user_id=1, source="test", type="user_message",
        text="Je suis pas dispo les 3 prochains jours, déplacement boulot.",
        payload={}, occurred_at=datetime(2026, 6, 1, 9, 0, tzinfo=PARIS),
    )
    return state, event


def _fais_ma_semaine() -> tuple[dict, InputEvent]:
    # propose_week POSITIVE case via the full runtime (recent done week + empty upcoming).
    state = {
        "today": "2026-06-08",
        "sessions": [
            {"id": 1, "date": "2026-06-02", "sport": "run", "title": "Footing", "duration_min": 45, "intensity_label": "easy", "priority": "optional", "status": "done"},
            {"id": 2, "date": "2026-06-04", "sport": "run", "title": "Seuil 3x8", "duration_min": 60, "intensity_label": "hard", "priority": "key", "status": "done"},
            {"id": 3, "date": "2026-06-07", "sport": "run", "title": "Sortie longue", "duration_min": 90, "intensity_label": "moderate", "priority": "key", "status": "done"},
        ],
    }
    event = InputEvent(
        id="evt-semaine", user_id=1, source="test", type="user_message",
        text="Fais-moi ma semaine prochaine.",
        payload={}, occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=PARIS),
    )
    return state, event


def _run(name: str, state: dict, event: InputEvent, expected: str, deps_factory, out_dir: Path) -> bool:
    db = out_dir / f"reg-{name}.db"
    seed_db(db, state)
    deps = deps_factory(db)
    result = handle_event(event, deps, turn_id=f"reg-{name}")
    rt = result.runtime_result
    tools = [c.get("name") for c in result.proposal.tool_trace]
    called_week = "propose_week" in tools or rt.proposal_type == "week_proposal"
    ok = rt.proposal_type in expected.split("|")
    # propose_week must ONLY appear on the explicit week-planning intent.
    week_ok = (name == "fais_ma_semaine") or (not called_week)
    verdict = "OK" if (ok and week_ok) else "‼️ REGRESSION"
    print(f"  [{verdict}] {name:22} expected={expected:28} got={rt.proposal_type:18} policy={rt.policy_action:16} week_called={called_week} tools={tools}")
    print(f"           reply: {result.reply[:140]}")
    return ok and week_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Couche-2 regression probe (real provider)")
    parser.add_argument("--provider", default="deepseek")
    args = parser.parse_args()
    try:
        coach = build_provider_client(args.provider, max_tokens=1024)
        gen = build_provider_client(args.provider, max_tokens=4096)
        reply = build_provider_client(args.provider, max_tokens=4096)
    except ProviderConfigError as exc:
        print(f"provider_config_error: {exc}\nHint: set -a && . ./.env && set +a")
        return 2
    model = getattr(getattr(coach, "profile", None), "model", "unknown")

    def deps_factory(db: Path) -> RuntimeDeps:
        return RuntimeDeps(
            db_path=db,
            coach_llm=MeteredLLMClient(coach, provider=args.provider, model=model),
            reply_llm=MeteredLLMClient(reply, provider=args.provider, model=model),
            generation_llm=MeteredLLMClient(gen, provider=args.provider, model=model),
        )

    out_dir = Path(tempfile.mkdtemp(prefix="v0-reg-"))
    print(f"REGRESSION PROBE  |  {args.provider}/{model}  |  out={out_dir}")
    print("=" * 100)
    passed = 0
    total = 0
    for name, expected in EXISTING:
        sc = scenario_by_name(name)
        total += 1
        passed += _run(name, sc.initial_db_state, sc.input_event, expected, deps_factory, out_dir)
    for name, builder, expected in [
        ("indispo_3_jours", _indispo_3_jours, "memory_update|plan_patch|ask_clarification"),
        ("fais_ma_semaine", _fais_ma_semaine, "week_proposal"),
    ]:
        state, event = builder()
        total += 1
        passed += _run(name, state, event, expected, deps_factory, out_dir)
    print("=" * 100)
    print(f"RESULT: {passed}/{total} held (no regression + propose_week only on the week intent)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
