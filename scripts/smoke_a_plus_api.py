#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"

Expectation = Literal["guarded_no_commit", "no_plan_write", "coherent_commit_or_pending"]


@dataclass(frozen=True, slots=True)
class SmokeScenario:
    name: str
    prompt: str
    expectation: Expectation
    description: str = ""


@dataclass(frozen=True, slots=True)
class DbSnapshot:
    events: tuple[dict[str, Any], ...]
    pending: tuple[dict[str, Any], ...]
    sessions: tuple[dict[str, Any], ...]
    latest_turn: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ScenarioCheckResult:
    ok: bool
    reasons: list[str]
    warnings: list[str]


SCENARIOS: tuple[SmokeScenario, ...] = (
    SmokeScenario(
        name="move_hard_close",
        prompt="Deplace la seance id 2 'Sortie longue cle' de jeudi a mercredi.",
        expectation="guarded_no_commit",
        description="Regression A+: a risky hard/key move must not bypass WeekCoherence.",
    ),
    SmokeScenario(
        name="replace_key_running_swim_easy",
        prompt="Remplace la seance id 1 'Fractionne seuil' par une natation easy.",
        expectation="guarded_no_commit",
        description="Regression A+: key running stimulus replaced by easy swimming must stay pending/block.",
    ),
    SmokeScenario(
        name="add_hard_dense",
        prompt="Ajoute une seance dure mercredi, meme si la semaine est deja chargee.",
        expectation="guarded_no_commit",
        description="Dense hard-session creation should not commit silently.",
    ),
    SmokeScenario(
        name="occupied_target",
        prompt="Deplace la seance id 2 'Sortie longue cle' de jeudi a samedi.",
        expectation="guarded_no_commit",
        description="Occupied target day should be blocked or pending, never committed.",
    ),
    SmokeScenario(
        name="memory_preference",
        prompt="A partir de maintenant, je prefere courir le matin quand c'est possible.",
        expectation="no_plan_write",
        description="Memory/preference turn must not create planning writes.",
    ),
    SmokeScenario(
        name="move_easy_to_free",
        prompt="Deplace la seance recuperation id 3 a lundi prochain.",
        expectation="coherent_commit_or_pending",
        description="Low-risk planning turn may commit or ask confirmation, but must stay artifact-coherent.",
    ),
)

_PENDING_OR_BLOCKED_MODES = {
    "plan_patch_confirmation",
    "mutation_confirmation",
    "plan_patch_blocked",
    "mutation_blocked",
    "pending_accepted",
    "pending_accept_blocked",
}
_MUTATION_CLAIM_MARKERS = (
    "c'est deplace",
    "c est deplace",
    "je l'ai deplace",
    "j ai deplace",
    "c'est remplace",
    "c est remplace",
    "j'ai remplace",
    "j ai remplace",
    "c'est cale",
    "c est cale",
    "j'ai cale",
    "j ai cale",
    "c'est ajoute",
    "c est ajoute",
    "j'ai ajoute",
    "j ai ajoute",
    "modification appliquee",
    "changement applique",
    "je l'ai mis",
    "j ai mis",
)


def evaluate_scenario_result(
    scenario: SmokeScenario,
    before: DbSnapshot,
    after: DbSnapshot,
) -> ScenarioCheckResult:
    reasons: list[str] = []
    warnings: list[str] = []
    event_delta = _row_delta(before.events, after.events)
    pending_delta = _row_delta(before.pending, after.pending)
    latest_turn = after.latest_turn or {}
    response_mode = str(latest_turn.get("response_mode") or "")
    assistant_message = str(latest_turn.get("assistant_message") or "")
    mutation_applied = bool(latest_turn.get("mutation_applied"))
    pending_confirmation = bool(latest_turn.get("pending_confirmation"))
    new_pending = _new_rows(before.pending, after.pending)
    if _contains_bracket_placeholder(assistant_message):
        warnings.append("assistant reply contains bracket placeholder")

    if scenario.expectation == "guarded_no_commit":
        if event_delta:
            reasons.append(f"wrote {event_delta} plan mutation event")
        if mutation_applied:
            reasons.append("latest turn marked mutation_applied")
        if new_pending and not any(str(row.get("mutation_type") or "") == "plan_patch" for row in new_pending):
            reasons.append("created pending confirmation outside plan_patch")
        if (
            not event_delta
            and not pending_delta
            and not pending_confirmation
            and response_mode not in _PENDING_OR_BLOCKED_MODES
            and _looks_like_mutation_claim(assistant_message)
        ):
            reasons.append("assistant claimed a mutation without event or pending confirmation")

    elif scenario.expectation == "no_plan_write":
        if event_delta:
            reasons.append(f"wrote {event_delta} plan mutation event")
        if pending_delta:
            reasons.append(f"created {pending_delta} pending confirmation")
        if mutation_applied:
            reasons.append("latest turn marked mutation_applied")
        if _looks_like_mutation_claim(assistant_message):
            reasons.append("assistant claimed a planning mutation on a no-write scenario")

    elif scenario.expectation == "coherent_commit_or_pending":
        if mutation_applied and not event_delta:
            reasons.append("latest turn marked mutation_applied without plan mutation event")
        if not event_delta and not pending_delta and not pending_confirmation:
            if _looks_like_mutation_claim(assistant_message):
                reasons.append("assistant claimed a mutation without event or pending confirmation")

    else:
        reasons.append(f"unknown expectation {scenario.expectation!r}")

    return ScenarioCheckResult(ok=not reasons, reasons=reasons, warnings=warnings)


def _row_delta(before_rows: tuple[dict[str, Any], ...], after_rows: tuple[dict[str, Any], ...]) -> int:
    return len(_new_rows(before_rows, after_rows))


def _new_rows(
    before_rows: tuple[dict[str, Any], ...],
    after_rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    before_ids = {row.get("id") for row in before_rows if row.get("id") is not None}
    if before_ids:
        return tuple(row for row in after_rows if row.get("id") not in before_ids)
    if len(after_rows) <= len(before_rows):
        return ()
    return tuple(after_rows[len(before_rows) :])


def _looks_like_mutation_claim(message: str) -> bool:
    if _looks_like_backend_action_claim(message):
        return True
    normalized = _normalize(message)
    return any(marker in normalized for marker in _MUTATION_CLAIM_MARKERS)


def _looks_like_backend_action_claim(message: str) -> bool:
    try:
        if str(BACKEND_SRC) not in sys.path:
            sys.path.insert(0, str(BACKEND_SRC))
        from fitmas.claim_guard import looks_like_action_claim
    except Exception:
        return False
    return looks_like_action_claim(message)


def _contains_bracket_placeholder(message: str) -> bool:
    normalized = _normalize(message)
    placeholders = ("[jour]", "[seance", "[autre", "[sortie", "[session")
    return any(marker in normalized for marker in placeholders)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.lower().split())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real HTTP + real LLM A+ WeekCoherence smoke scenarios."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in SCENARIOS],
        help="Run only this scenario. Repeatable.",
    )
    parser.add_argument("--port", type=int, default=8073, help="First localhost port to try.")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=ROOT / f".tmp-smoke-a-plus-api-{os.getpid()}.db",
        help="SQLite DB path for the isolated smoke run.",
    )
    parser.add_argument("--keep-db", action="store_true", help="Keep the smoke DB after the run.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for each real API call.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for the local API to become healthy.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv or sys.argv[1:])
    db_path = args.db_path.resolve()
    selected = _selected_scenarios(args.scenario)
    port = _choose_port(args.port)
    base_url = f"http://127.0.0.1:{port}"
    log_path = ROOT / f".tmp-smoke-a-plus-api-{os.getpid()}.log"

    os.environ["FITMAS_DB_PATH"] = str(db_path)
    os.environ.setdefault("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", "1")
    if not os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]

    print(f"A+ API smoke: {len(selected)} scenario(s)")
    print(f"DB: {db_path}")
    print(f"API: {base_url}")
    print(f"log: {log_path}")
    print("")

    _reset_and_seed_database(db_path)
    server, log_file = _start_server(port=port, db_path=db_path, log_path=log_path)
    try:
        _wait_for_health(base_url, timeout_seconds=args.startup_timeout)
        failures = 0
        for scenario in selected:
            _reset_and_seed_database(db_path)
            before = load_db_snapshot(db_path)
            print(f"SCENARIO {scenario.name}")
            print(f"prompt: {scenario.prompt}")
            try:
                response = _post_message(base_url, scenario.prompt, timeout_seconds=args.timeout)
                assistant_text = _assistant_text_from_response(response)
                print(f"assistant: {assistant_text}")
            except Exception as exc:  # pragma: no cover - exercised by real smoke only
                failures += 1
                print(f"FAIL: HTTP/LLM error: {exc}")
                print("")
                continue

            after = load_db_snapshot(db_path)
            result = evaluate_scenario_result(scenario, before, after)
            _print_artifacts(before, after)
            if result.ok:
                print("OK")
            else:
                failures += 1
                print("FAIL")
                for reason in result.reasons:
                    print(f"- {reason}")
            for warning in result.warnings:
                print(f"WARN: {warning}")
            print("")

        if failures:
            print(f"RESULT: FAIL ({failures}/{len(selected)} scenario(s))")
            print(f"server log: {log_path}")
            return 1
        print(f"RESULT: OK ({len(selected)} scenario(s))")
        return 0
    finally:
        _stop_server(server)
        log_file.close()
        if not args.keep_db:
            _unlink_if_exists(db_path)
        _unlink_if_exists(db_path.with_suffix(db_path.suffix + "-journal"))


def _selected_scenarios(names: list[str] | None) -> tuple[SmokeScenario, ...]:
    if not names:
        return SCENARIOS
    by_name = {scenario.name: scenario for scenario in SCENARIOS}
    return tuple(by_name[name] for name in names)


def _choose_port(start_port: int) -> int:
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"no free localhost port from {start_port} to {start_port + 49}")


def _start_server(
    *,
    port: int,
    db_path: Path,
    log_path: Path,
) -> tuple[subprocess.Popen[bytes], Any]:
    env = os.environ.copy()
    env["FITMAS_DB_PATH"] = str(db_path)
    env.setdefault("FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED", "1")
    if not env.get("ANTHROPIC_API_KEY") and env.get("DEEPSEEK_API_KEY"):
        env["ANTHROPIC_API_KEY"] = env["DEEPSEEK_API_KEY"]
    log_file = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--app-dir",
            str(BACKEND_SRC),
            "fitmas.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return process, log_file


def _wait_for_health(base_url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2.0) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - timing dependent
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"API did not become healthy: {last_error}")


def _post_message(base_url: str, prompt: str, *, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps({"text": prompt}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/v0/messages",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _assistant_text_from_response(response: dict[str, Any]) -> str:
    message = response.get("assistant_message")
    if isinstance(message, dict):
        return str(message.get("text") or "")
    return str(message or "")


def _print_artifacts(before: DbSnapshot, after: DbSnapshot) -> None:
    event_delta = _row_delta(before.events, after.events)
    pending_delta = _row_delta(before.pending, after.pending)
    latest_turn = after.latest_turn or {}
    session_changes = _session_changes(before.sessions, after.sessions)
    print(
        "artifacts: "
        f"events=+{event_delta} "
        f"pending=+{pending_delta} "
        f"mode={latest_turn.get('response_mode') or '-'} "
        f"mutation_applied={bool(latest_turn.get('mutation_applied'))} "
        f"session_changes={len(session_changes)}"
    )
    for row in _new_rows(before.events, after.events):
        print(f"  event#{row.get('id')}: {row.get('command_type') or '-'} {row.get('target_session_ids_json') or ''}")
    for row in _new_rows(before.pending, after.pending):
        print(f"  pending#{row.get('id')}: {row.get('mutation_type') or '-'} {row.get('reason') or ''}")
    for change in session_changes:
        print(f"  session#{change['id']}: {change['before']} -> {change['after']}")


def _session_changes(
    before_rows: tuple[dict[str, Any], ...],
    after_rows: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    before = {row.get("id"): row for row in before_rows}
    changes: list[dict[str, Any]] = []
    for row in after_rows:
        row_id = row.get("id")
        old = before.get(row_id)
        if old is None:
            changes.append({"id": row_id, "before": "<new>", "after": _session_summary(row)})
        elif _session_summary(old) != _session_summary(row):
            changes.append({"id": row_id, "before": _session_summary(old), "after": _session_summary(row)})
    return changes


def _session_summary(row: dict[str, Any]) -> str:
    return (
        f"{row.get('scheduled_date') or '-'} | "
        f"{row.get('session_title') or '-'} | "
        f"{row.get('sport_type') or '-'} | "
        f"{row.get('session_type') or '-'} | "
        f"{row.get('intensity') or '-'} | "
        f"{row.get('completion_status') or '-'}"
    )


def load_db_snapshot(db_path: Path) -> DbSnapshot:
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        return DbSnapshot(
            events=_fetch_all(
                connection,
                """
                select id, source, trigger_type, command_type, target_session_ids_json,
                       user_visible_summary, created_at
                from plan_mutation_events
                order by id
                """,
            ),
            pending=_fetch_all(
                connection,
                """
                select id, status, reason, mutation_type, summary, decision_json, created_at
                from pending_mutation_confirmations
                order by id
                """,
            ),
            sessions=_fetch_all(
                connection,
                """
                select id, scheduled_date, day, session_title, sport_type, session_type,
                       intensity, duration_min, priority, completion_status
                from scheduled_sessions
                order by id
                """,
            ),
            latest_turn=_fetch_one(
                connection,
                """
                select id, user_message, assistant_message, response_mode, mutation_type,
                       mutation_applied, pending_confirmation, pending_confirmation_id, created_at
                from conversation_turns
                order by id desc
                limit 1
                """,
            ),
        )


def _fetch_all(connection: sqlite3.Connection, query: str) -> tuple[dict[str, Any], ...]:
    try:
        rows = connection.execute(query).fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(_row_to_dict(row) for row in rows)


def _fetch_one(connection: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    try:
        row = connection.execute(query).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return _row_to_dict(row)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("mutation_applied", "pending_confirmation"):
        if key in result:
            result[key] = bool(result[key])
    return result


def _reset_and_seed_database(db_path: Path) -> None:
    os.environ["FITMAS_DB_PATH"] = str(db_path)
    if str(BACKEND_SRC) not in sys.path:
        sys.path.insert(0, str(BACKEND_SRC))

    from fitmas import repository as repo
    from fitmas import schema as s
    from fitmas.db import Base, SessionLocal, engine, init_db
    from fitmas.time_context import DAY_KEYS, day_label_fr, get_local_now

    db_path.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    init_db()

    with SessionLocal() as db:
        user = s.User(
            name="Loic",
            timezone="Europe/Paris",
            age=31,
            primary_objective="10 km propre sans casser la semaine",
            objective="10 km propre sans casser la semaine",
            weekly_structure_notes=(
                "Mercredi qualite course, jeudi sortie longue, vendredi recuperation, "
                "samedi velo facile, dimanche natation."
            ),
            coach_name="Aster",
            coach_style="direct",
            coach_relationship="lucide et stable",
            coach_do="proteger les seances cles et la recuperation",
            coach_dont="committer un compromis sportif fragile sans confirmation",
            coach_soul="sobre, precis, fiable",
            onboarding_status="completed",
        )
        db.add(user)
        db.flush()
        for rank, sport in enumerate(("running", "cycling", "swimming", "strength")):
            db.add(s.UserSport(user_id=user.id, sport_type=sport, priority_rank=rank, active=True))
        db.add(s.UserPreference(user_id=user.id, text="matin > soir"))
        db.add(s.UserConstraint(user_id=user.id, text="semaine deja dense, proteger la recuperation"))
        db.add(
            s.UserFact(
                user_id=user.id,
                category="training_state",
                key="current_state",
                value="forme correcte mais charge recente moderee, pas de double intensite inutile",
                source="a_plus_smoke",
                confidence=0.9,
                confirmed=True,
                active=True,
                urgency="medium",
                ttl="medium",
                affects_json='["planning","conversation","heartbeat"]',
            )
        )

        now = get_local_now(user.timezone)
        wednesday = _next_weekday_date(now, target_weekday=2)
        sessions = (
            _session_payload(
                s,
                user_id=user.id,
                target=wednesday.replace(hour=8, minute=0, second=0, microsecond=0),
                title="Fractionne seuil",
                sport_type="running",
                session_type="threshold",
                intensity="hard",
                duration_min=65,
                priority="Seance cle",
                goal="Stimulus course principal",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0),
                title="Sortie longue cle",
                sport_type="running",
                session_type="long",
                intensity="hard",
                duration_min=95,
                priority="Seance cle",
                goal="Endurance specifique",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=2)).replace(hour=8, minute=0, second=0, microsecond=0),
                title="Recuperation mobilite",
                sport_type="strength",
                session_type="recovery",
                intensity="easy",
                duration_min=30,
                priority="Support",
                goal="Absorber la charge",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0),
                title="Velo facile",
                sport_type="cycling",
                session_type="easy",
                intensity="easy",
                duration_min=50,
                priority="Support",
                goal="Aerobie douce",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
            _session_payload(
                s,
                user_id=user.id,
                target=(wednesday + timedelta(days=4)).replace(hour=9, minute=0, second=0, microsecond=0),
                title="Natation technique",
                sport_type="swimming",
                session_type="easy",
                intensity="easy",
                duration_min=40,
                priority="Support",
                goal="Technique sans fatigue",
                day_keys=DAY_KEYS,
                day_label_fr=day_label_fr,
                source_plan_created_at=now,
            ),
        )
        db.add_all(sessions)
        db.commit()

        for sport_type, title, duration_min, days_ago, tss in (
            ("running", "Footing controle", 45, 3, 32.0),
            ("cycling", "Endurance velo", 70, 6, 38.0),
            ("running", "Tempo propre", 55, 9, 48.0),
        ):
            repo.add_activity(
                db,
                user_id=user.id,
                source="manual",
                scheduled_session_id=None,
                sport_type=sport_type,
                title=title,
                duration_min=duration_min,
                distance_m=0,
                elevation_m=0,
                perceived_load=3,
                note="a_plus_smoke",
                started_at=now - timedelta(days=days_ago),
                matched_day=None,
                match_reason="a_plus_smoke",
                tss=tss,
            )


def _next_weekday_date(now: datetime, *, target_weekday: int) -> datetime:
    delta = (target_weekday - now.weekday()) % 7
    if delta == 0:
        delta = 7
    return now + timedelta(days=delta)


def _session_payload(
    schema_module: Any,
    *,
    user_id: int,
    target: datetime,
    title: str,
    sport_type: str,
    session_type: str,
    intensity: str,
    duration_min: int,
    priority: str,
    goal: str,
    day_keys: list[str],
    day_label_fr: Any,
    source_plan_created_at: datetime,
) -> Any:
    day_key = day_keys[target.weekday()]
    return schema_module.ScheduledSession(
        user_id=user_id,
        day=day_key,
        label=day_label_fr(day_key, capitalize=True),
        scheduled_date=target.replace(tzinfo=None),
        source_plan_created_at=source_plan_created_at.replace(tzinfo=None),
        sport_type=sport_type,
        session_type=session_type,
        session_title=title,
        session_goal=goal,
        session_note="smoke A+",
        session_description=f"{duration_min} min",
        duration_min=duration_min,
        intensity=intensity,
        load_score=5 if intensity == "hard" else 2,
        priority=priority,
        nutrition_focus="",
        flexibility="stable" if priority == "Seance cle" else "flexible",
        completion_status="planned",
    )


def _stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:  # pragma: no cover - timing dependent
        process.kill()
        process.wait(timeout=5)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
