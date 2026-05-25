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
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("No failures.")
    else:
        for record in failures:
            lines.append(
                f"- `{record.turn_id}` {record.provider}/{record.scenario}/{record.repetition}: "
                f"{', '.join(record.failures)}"
            )
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
