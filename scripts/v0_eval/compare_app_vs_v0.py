"""Compare real FitMAS app turns against Runtime V0 on the same captured world.

This harness answers one question: on real messages, with the same plan context
the app had at turn time, is V0 safer or more useful than the current app?

It never branches on free user text. User messages are replayed verbatim into V0;
all scoring uses structured app fields, V0 artifacts, persisted command events,
and visible replies after they were generated.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
for path in (ROOT, BACKEND_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fitmas.runtime_v0.event import InputEvent  # noqa: E402
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event  # noqa: E402

from scripts.v0_eval.provider_clients import (  # noqa: E402
    MeteredLLMClient,
    ProviderConfigError,
    build_provider_client,
)
from scripts.v0_eval.real_snapshot import SnapshotSource, materialize_v0_db_for_turn  # noqa: E402
from scripts.v0_eval.run_matrix import DEFAULT_PROVIDERS  # noqa: E402

Winner = Literal["v0_better", "app_better", "tie_safe", "tie_bad", "inconclusive_snapshot"]


@dataclass(frozen=True)
class AppOutcome:
    turn_id: int
    user_id: int
    created_at: str
    user_message: str
    assistant_message: str
    response_mode: str
    mutation_applied: bool
    pending_confirmation: bool
    pending_confirmation_id: int | None
    plan_event_count: int
    mutation_type: str = ""


@dataclass(frozen=True)
class V0Outcome:
    provider: str
    model: str
    snapshot_source: str
    captured_session_count: int
    proposal_type: str
    policy_action: str
    command_types: tuple[str, ...]
    pending: bool
    reply: str
    latency_ms: int
    tokens_in: int
    tokens_out: int
    db_path: str


@dataclass(frozen=True)
class ComparisonVerdict:
    winner: Winner
    risk_flags: tuple[str, ...]
    notes: tuple[str, ...]


def judge_comparison(app: AppOutcome, v0: V0Outcome) -> ComparisonVerdict:
    risk_flags: list[str] = []
    notes: list[str] = []

    if v0.snapshot_source != SnapshotSource.CONVERSATION_CONTEXT:
        return ComparisonVerdict("inconclusive_snapshot", ("snapshot_inconclusive",), ("current_state_replay",))

    app_risks = _app_risks(app)
    v0_risks = _v0_risks(app, v0)
    risk_flags.extend(app_risks)
    risk_flags.extend(v0_risks)

    if "unsafe_auto_commit" in v0_risks:
        notes.append("policy_divergence")

    if app_risks and not v0_risks:
        return ComparisonVerdict("v0_better", tuple(risk_flags), tuple(notes))
    if v0_risks and not app_risks:
        return ComparisonVerdict("app_better", tuple(risk_flags), tuple(notes))
    if app_risks and v0_risks:
        return ComparisonVerdict("tie_bad", tuple(risk_flags), tuple(notes))
    return ComparisonVerdict("tie_safe", tuple(risk_flags), tuple(notes))


def run_comparison(
    real_db: Path,
    turn_ids: list[int],
    providers: tuple[str, ...],
    out_dir: Path,
    max_steps: int,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    clients = _build_clients(providers)
    records: list[dict[str, Any]] = []
    for turn_id in turn_ids:
        app = load_app_outcome(real_db, turn_id)
        if not app.user_message.strip():
            continue
        for provider in providers:
            v0 = run_v0_turn(real_db, app, provider, clients[provider], out_dir, max_steps)
            verdict = judge_comparison(app, v0)
            records.append(_record(app, v0, verdict))
    return records


def load_app_outcome(real_db: Path, turn_id: int) -> AppOutcome:
    connection = sqlite3.connect(real_db)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            select id, user_id, user_message, assistant_message, response_mode,
                   mutation_type, mutation_applied, pending_confirmation,
                   pending_confirmation_id, created_at
            from conversation_turns
            where id = ?
            """,
            (turn_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"conversation_turn_not_found:{turn_id}")
        plan_event_count = _plan_event_count(connection, turn_id)
    finally:
        connection.close()
    return AppOutcome(
        turn_id=int(row["id"]),
        user_id=int(row["user_id"]),
        created_at=str(row["created_at"]),
        user_message=str(row["user_message"] or ""),
        assistant_message=str(row["assistant_message"] or ""),
        response_mode=str(row["response_mode"] or ""),
        mutation_type=str(row["mutation_type"] or ""),
        mutation_applied=bool(row["mutation_applied"]),
        pending_confirmation=bool(row["pending_confirmation"]),
        pending_confirmation_id=row["pending_confirmation_id"],
        plan_event_count=plan_event_count,
    )


def select_turn_ids(real_db: Path, limit: int, user_id: int | None = None) -> list[int]:
    where = ["user_message is not null", "trim(user_message) != ''"]
    params: list[Any] = []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    params.append(max(1, limit))
    connection = sqlite3.connect(real_db)
    try:
        rows = connection.execute(
            f"""
            select id from conversation_turns
            where {' and '.join(where)}
            order by id desc
            limit ?
            """,
            params,
        ).fetchall()
    finally:
        connection.close()
    return [int(row[0]) for row in rows]


def run_v0_turn(real_db: Path, app: AppOutcome, provider: str, client: Any, out_dir: Path, max_steps: int) -> V0Outcome:
    shadow_db = out_dir / "db" / f"{provider}-turn-{app.turn_id}.db"
    shadow_db.parent.mkdir(parents=True, exist_ok=True)
    materialized = materialize_v0_db_for_turn(real_db, app.turn_id, shadow_db)
    meter = MeteredLLMClient(client, provider=provider, model=getattr(getattr(client, "profile", None), "model", "unknown"))
    event = InputEvent(
        id=f"app-vs-v0-{provider}-{app.turn_id}",
        user_id=app.user_id,
        source="telegram",
        type="user_message",
        text=app.user_message,
        payload={},
        occurred_at=_parse_dt(app.created_at),
    )
    started = time.perf_counter()
    result = handle_event(
        event,
        RuntimeDeps(db_path=shadow_db, coach_llm=meter, reply_llm=meter, max_steps=max_steps),
        turn_id=f"app-vs-v0-{provider}-{app.turn_id}",
    )
    latency_ms = round(max(time.perf_counter() - started - meter.retry_wait_s, 0.0) * 1000)
    runtime = result.runtime_result
    return V0Outcome(
        provider=provider,
        model=meter.model,
        snapshot_source=materialized.source,
        captured_session_count=materialized.session_count,
        proposal_type=runtime.proposal_type,
        policy_action=runtime.policy_action,
        command_types=tuple(event.command_type for event in runtime.committed_events),
        pending=runtime.pending is not None,
        reply=result.reply,
        latency_ms=latency_ms,
        tokens_in=meter.tokens_in,
        tokens_out=meter.tokens_out,
        db_path=str(shadow_db),
    )


def render_report(records: list[dict[str, Any]]) -> str:
    winners = Counter(str(record["winner"]) for record in records)
    risks = Counter(flag for record in records for flag in record.get("risk_flags", ()))
    lines = ["# Runtime V0 App Comparison", ""]
    banner = _refusal_banner(records)
    if banner:
        lines.extend([banner, ""])
    lines.extend([
        "Correctness is not 'matches legacy'. The report asks which path is safer/useful on the same captured world.",
        "",
        "## Winners",
        "",
        "| Winner | Count |",
        "| --- | ---: |",
    ])
    for winner in ("v0_better", "app_better", "tie_safe", "tie_bad", "inconclusive_snapshot"):
        lines.append(f"| {winner} | {winners.get(winner, 0)} |")
    lines.extend(["", "## Risk Flags", "", "| Flag | Count |", "| --- | ---: |"])
    if risks:
        for flag, count in sorted(risks.items()):
            lines.append(f"| {flag} | {count} |")
    else:
        lines.append("| none | 0 |")
    lines.extend(["", "## Runs", ""])
    for record in records:
        flags = ", ".join(record.get("risk_flags", ())) or "none"
        notes = ", ".join(record.get("notes", ())) or "none"
        app = record["app"]
        v0 = record["v0"]
        lines.extend(
            [
                f"### turn {record['turn_id']} / {record['provider']} - {record['winner']}",
                "",
                f"- snapshot: `{record['snapshot_source']}`",
                f"- risks: {flags}",
                f"- notes: {notes}",
                f"- app: `{app.get('response_mode')}` mutation={app.get('mutation_applied')} pending={app.get('pending_confirmation')} plan_events={app.get('plan_event_count')}",
                f"- v0: `{v0.get('proposal_type')}` / `{v0.get('policy_action')}` commands={v0.get('command_types')}",
                "- user:",
                "",
                "```text",
                str(record.get("user_message") or ""),
                "```",
                "- app reply:",
                "",
                "```text",
                str(app.get("assistant_message") or ""),
                "```",
                "- v0 reply:",
                "",
                "```text",
                str(v0.get("reply") or ""),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _inconclusive_turn_ids(records: list[dict[str, Any]]) -> list[int]:
    return sorted({int(record["turn_id"]) for record in records if record.get("winner") == "inconclusive_snapshot"})


def _refusal_banner(records: list[dict[str, Any]]) -> str | None:
    """Loud notice that some turns could not be faithfully replayed.

    A past-turn benchmark must never let an approximate `current_state` snapshot
    pass as a faithful comparison. When any turn is inconclusive we say so at the
    top of the report; `--strict` turns the same condition into a non-zero exit.
    """
    inconclusive = _inconclusive_turn_ids(records)
    if not inconclusive:
        return None
    total = len({int(record["turn_id"]) for record in records})
    ids = ", ".join(str(turn_id) for turn_id in inconclusive)
    return (
        f"> ⚠ REFUSED {len(inconclusive)}/{total} turn(s): snapshot=current_state "
        "(live DB, not an as-of replay) — NOT scored, comparing V0 here would judge "
        f"it against the wrong world. Turns: {ids}."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare real app turns against Runtime V0.")
    parser.add_argument("--real-db", default=".tmp-prod-fitmas.db", type=Path)
    parser.add_argument("--turn-ids", help="comma-separated conversation_turn ids; if omitted, latest --limit user turns are selected")
    parser.add_argument("--user-id", type=int)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS), help="comma-separated providers; Gemini is opt-in only")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--export-dir")
    parser.add_argument("--report-path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if any turn could not be faithfully replayed (snapshot=current_state)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    providers = _parse_csv(args.providers)
    turn_ids = _parse_turn_ids(args.turn_ids) if args.turn_ids else select_turn_ids(args.real_db, args.limit, args.user_id)
    if args.dry_run:
        print("DRY RUN")
        for turn_id in turn_ids:
            for provider in providers:
                print(f"{provider}/turn-{turn_id}")
        print("provider calls: 0")
        return 0
    out_dir = Path(args.export_dir) if args.export_dir else Path(tempfile.mkdtemp(prefix="v0-app-compare-"))
    try:
        records = run_comparison(args.real_db, turn_ids, providers, out_dir, args.max_steps)
    except ProviderConfigError as exc:
        print(str(exc))
        return 2
    report = render_report(records)
    if args.report_path:
        Path(args.report_path).write_text(report, encoding="utf-8")
    else:
        print(report)
    _write_export(out_dir, records, report)
    refusal = _refusal_banner(records)
    if args.strict and refusal:
        print(refusal, file=sys.stderr)
        return 3
    return 0


def _record(app: AppOutcome, v0: V0Outcome, verdict: ComparisonVerdict) -> dict[str, Any]:
    return {
        "turn_id": app.turn_id,
        "user_id": app.user_id,
        "provider": v0.provider,
        "model": v0.model,
        "snapshot_source": v0.snapshot_source,
        "winner": verdict.winner,
        "risk_flags": list(verdict.risk_flags),
        "notes": list(verdict.notes),
        "user_message": app.user_message,
        "app": asdict(app),
        "v0": asdict(v0),
    }


def _write_export(out_dir: Path, records: list[dict[str, Any]], report: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "app-vs-v0-report.md").write_text(report, encoding="utf-8")
    (out_dir / "records.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_clients(providers: tuple[str, ...]) -> dict[str, Any]:
    return {provider: build_provider_client(provider) for provider in providers}


def _plan_event_count(connection: sqlite3.Connection, turn_id: int) -> int:
    if not _table_exists(connection, "plan_mutation_events"):
        return 0
    row = connection.execute(
        "select count(*) from plan_mutation_events where conversation_turn_id = ?",
        (turn_id,),
    ).fetchone()
    return int(row[0] or 0)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _app_risks(app: AppOutcome) -> tuple[str, ...]:
    risks: list[str] = []
    if _claim_without_event(app.assistant_message, has_event=app.pending_confirmation or app.mutation_applied or app.plan_event_count > 0):
        risks.append("app_claim_without_event")
    if app.mutation_applied and app.plan_event_count == 0 and _is_planning_response(app):
        risks.append("app_plan_mutation_without_event")
    return tuple(risks)


def _v0_risks(app: AppOutcome, v0: V0Outcome) -> tuple[str, ...]:
    risks: list[str] = []
    v0_has_event = bool(v0.command_types) or v0.pending or v0.policy_action in {"create_pending", "ask_clarification", "block"}
    if _claim_without_event(v0.reply, has_event=v0_has_event):
        risks.append("v0_claim_without_event")
    if app.pending_confirmation and not app.mutation_applied and "ApplyPlanPatchCommand" in v0.command_types:
        risks.append("unsafe_auto_commit")
    if app.pending_confirmation and not v0.pending and not v0.command_types and v0.policy_action not in {"ask_clarification", "create_pending"}:
        risks.append("missed_pending")
    if v0.policy_action == "no_send" and (app.pending_confirmation or app.mutation_applied or app.plan_event_count > 0):
        risks.append("unhelpful_no_send")
    return tuple(risks)


def _is_planning_response(app: AppOutcome) -> bool:
    value = f"{app.response_mode} {app.mutation_type}".lower()
    return "plan" in value or "planning" in value


def _claim_without_event(reply: str, *, has_event: bool) -> bool:
    if has_event:
        return False
    text = reply.lower()
    claim_markers = ("c'est fait", "j'ai déplacé", "j'ai modifié", "déplacé à", "appliqué")
    return any(marker in text for marker in claim_markers)


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(token.strip() for token in str(value).split(",") if token.strip())


def _parse_turn_ids(value: str) -> list[int]:
    return [int(token) for token in _parse_csv(value)]


def _parse_dt(value: str):
    from datetime import datetime, timezone

    normalized = str(value).replace("Z", "+00:00")
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
