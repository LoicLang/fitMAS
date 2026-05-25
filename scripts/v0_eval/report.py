from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class MatrixRunRecord:
    scenario: str
    provider: str
    repetition: int
    success: bool
    latency_ms: int
    tokens_in: int
    tokens_out: int
    failures: tuple[str, ...]
    turn_id: str
    model: str | None = None
    db_path: str | None = None
    turn_count: int = 0
    guard_block_count: int = 0
    guard_repair_count: int = 0
    sanitized_fallback_count: int = 0
    raw_json_block_count: int = 0
    truncated_reply_count: int = 0
    technical_id_block_count: int = 0
    wrong_write_count: int = 0
    old_plan_date_count: int = 0
    wrong_correction_target_count: int = 0
    reply_claim_without_event_count: int = 0
    triage: tuple[str, ...] = ()


def render_markdown_report(records: list[MatrixRunRecord]) -> str:
    lines = [
        "# Runtime V0 Matrix Report",
        "",
        "## Summary",
        "",
        "| Scenario | Provider | Success | p50 latency | p95 latency | Avg tokens |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for (scenario, provider), group in sorted(_groups(records).items()):
        success_count = sum(1 for record in group if record.success)
        latencies = [record.latency_ms for record in group]
        tokens = [record.tokens_in + record.tokens_out for record in group]
        avg_tokens = round(sum(tokens) / len(tokens)) if tokens else 0
        lines.append(
            f"| {scenario} | {provider} | {success_count}/{len(group)} | "
            f"{_percentile(latencies, 50)}ms | {_percentile(latencies, 95)}ms | {avg_tokens} |"
        )

    failures = [record for record in records if not record.success]
    lines.extend(["", "## Quality Metrics", ""])
    lines.extend(_quality_metrics_lines(records))
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("No failures.")
    else:
        for record in failures:
            lines.append(
                f"- `{record.turn_id}` {record.provider}/{record.scenario}/{record.repetition}: "
                f"{', '.join(record.failures)}"
            )
    triage_records = [record for record in failures if record.triage]
    if triage_records:
        lines.extend(["", "## Failure Triage", ""])
        for record in triage_records:
            lines.append(f"### `{record.turn_id}` {record.provider}/{record.scenario}/{record.repetition}")
            lines.append("")
            lines.extend(f"- {item}" for item in record.triage)
            lines.append("")
    return "\n".join(lines) + "\n"


def _groups(records: list[MatrixRunRecord]) -> dict[tuple[str, str], list[MatrixRunRecord]]:
    groups: dict[tuple[str, str], list[MatrixRunRecord]] = defaultdict(list)
    for record in records:
        groups[(record.scenario, record.provider)].append(record)
    return groups


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile / 100)
    return ordered[index]

def _quality_metrics_lines(records: list[MatrixRunRecord]) -> list[str]:
    total_turns = sum(record.turn_count for record in records) or len(records) or 1
    metrics = (
        ("guard_block_rate", sum(record.guard_block_count for record in records), total_turns),
        ("guard_repair_rate", sum(record.guard_repair_count for record in records), total_turns),
        ("sanitized_fallback_rate", sum(record.sanitized_fallback_count for record in records), total_turns),
        ("raw_json_block_count", sum(record.raw_json_block_count for record in records), total_turns),
        ("truncated_reply_count", sum(record.truncated_reply_count for record in records), total_turns),
        ("technical_id_block_count", sum(record.technical_id_block_count for record in records), total_turns),
        ("wrong_write_count", sum(record.wrong_write_count for record in records), len(records) or 1),
        ("old_plan_date_count", sum(record.old_plan_date_count for record in records), len(records) or 1),
        ("wrong_correction_target_count", sum(record.wrong_correction_target_count for record in records), len(records) or 1),
        ("reply_claim_without_event_count", sum(record.reply_claim_without_event_count for record in records), len(records) or 1),
    )
    lines = ["| Metric | Count | Rate |", "| --- | ---: | ---: |"]
    lines.extend(f"| {name} | {count} | {_rate(count, denominator)} |" for name, count, denominator in metrics)
    return lines

def _rate(count: int, denominator: int) -> str:
    return f"{(count / max(denominator, 1)) * 100:.1f}%"
