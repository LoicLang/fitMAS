"""Offline 4-6 week Meso generation harness (couche 2, manual).

Chains: seed actuals -> build target -> generate_week (real provider) -> verify ->
reduce to actuals -> repeat. Prints each week + verdict for hand-verification vs the
app (the TSS-drop case). Not a unit test; needs a provider API key. Exports not committed.

Usage: .venv/bin/python scripts/v0_eval/generate_weeks.py --provider deepseek --weeks 5
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
for path in (ROOT, BACKEND_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fitmas.runtime_v0.meso.generator import generate_week
from fitmas.runtime_v0.meso.model import (
    ContextPack,
    WeekActuals,
    actuals_from_week,
    derive_continuity_target,
)
from scripts.v0_eval.provider_clients import MeteredLLMClient, ProviderConfigError, build_provider_client


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Meso week-generation harness")
    parser.add_argument("--provider", default="deepseek", help="Provider name (deepseek/mistral/grok/gemini)")
    parser.add_argument("--weeks", type=int, default=5, help="Number of weeks to chain (4-6 recommended)")
    args = parser.parse_args()

    try:
        raw_client = build_provider_client(args.provider)
    except ProviderConfigError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    llm = MeteredLLMClient(raw_client, provider=args.provider, model=raw_client.profile.model)

    # Seed: a realistic build week (threshold key, 300 load)
    actuals = WeekActuals(total_load=300.0, key_type="threshold")
    monday = date(2026, 6, 8)

    print(f"Harness: {args.provider} / {args.weeks} weeks starting {monday}")
    print(f"Seed actuals: load={actuals.total_load} key={actuals.key_type}")
    print()

    for week_idx in range(1, args.weeks + 1):
        target = derive_continuity_target(actuals)
        pack = ContextPack(
            target=target,
            last_week_actuals=actuals,
            constraints=(),
            signals=(),
        )

        print(f"=== Week {week_idx} — {monday} ===")
        print(f"  Target: phase={target.phase} key={target.key_type} band={target.load_band}")

        proposal = generate_week(llm, pack, monday)

        print(f"  Source: {proposal.source}  attempts={proposal.attempts}  ok={proposal.verdict.ok}")

        for session in proposal.week.sessions:
            print(
                f"    {session.date}  {session.type:<16}  {session.duration_min:>3}min"
                f"  {session.intensity:<8}  load={session.load:.0f}"
            )

        week_load = proposal.week.week_load
        low, high = target.load_band
        if week_load < low:
            band_label = "BELOW"
        elif week_load > high:
            band_label = "ABOVE"
        else:
            band_label = "in-band"

        print(f"  week_load={week_load:.0f}  band=[{low},{high}]  {band_label}")

        if proposal.verdict.violations:
            codes = ", ".join(v.code for v in proposal.verdict.violations)
            print(f"  violations: {codes}")

        print()

        # Forward-only chaining: reduce to actuals for the next iteration
        try:
            actuals = actuals_from_week(proposal.week)
        except ValueError as exc:
            print(f"  WARNING: cannot chain (actuals_from_week failed: {exc}); reusing seed actuals")

        monday = date.fromordinal(monday.toordinal() + 7)

    print(f"Done. calls={llm.calls} tokens_in={llm.tokens_in} tokens_out={llm.tokens_out} retry_wait={llm.retry_wait_s:.1f}s")


if __name__ == "__main__":
    main()
