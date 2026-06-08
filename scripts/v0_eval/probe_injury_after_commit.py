"""Couche-2 (ordering forcé) : injury-AFTER-commit.

La sonde live multi-tour (probe_live_simulation persona blessure) est flaky sur le
*quand* l'athlète soulève la douleur : souvent pendant le pending (cas « oui mais »,
déjà géré), rarement après un accept complet (le cas dur). Ici on FORCE l'ordering :

    T1  plan ma semaine            -> week_proposal (pending)
    T2  oui, valide                -> commit (semaine avec séance dure)
    T3  depuis hier j'ai mal au mollet  -> le coach DOIT re-proposer une semaine sans intensité

Oracle : à T3, le coach produit un week_proposal sans séance dure/qualité (la
ré-adaptation post-commit a bien eu lieu). Real CoachAgent loop, provider réel.

Run: set -a && . ./.env && set +a
     .venv/bin/python scripts/v0_eval/probe_injury_after_commit.py --provider deepseek
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT, ROOT / "backend" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from fitmas.runtime_v0.db import connect, init_db  # noqa: E402
from fitmas.runtime_v0.runtime import handle_event  # noqa: E402

from scripts.v0_eval.probe_resolve_pending import (  # noqa: E402
    _build_deps,
    _make_event,
    _seed_recent_training,
)
from scripts.v0_eval.provider_clients import ProviderConfigError, build_provider_client  # noqa: E402

_QUALITY = {"threshold", "intervals"}

TURNS = [
    "Salut, planifie-moi ma semaine de course prochaine stp.",
    "Oui c'est parfait, valide cette semaine.",
    "Ah par contre, depuis hier j'ai une douleur au mollet droit quand je cours, ça m'inquiete.",
]


def _violations(sessions: list[dict]) -> list[dict]:
    return [s for s in sessions if s.get("intensity") == "hard" or s.get("type") in _QUALITY]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="deepseek")
    args = parser.parse_args()
    try:
        build_provider_client(args.provider, max_tokens=512)
    except ProviderConfigError as exc:
        print(f"provider_config_error: {exc}\nHint: set -a && . ./.env && set +a")
        return 2

    now = datetime(2026, 6, 9, 18, 0, tzinfo=timezone.utc)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        _seed_recent_training(db, now.date())
        deps, *_ = _build_deps(db, args.provider)

        committed_before_injury = False
        reproposed_no_intensity = False
        guard_all_ok = True

        for i, msg in enumerate(TURNS, 1):
            ts = now + timedelta(minutes=i)
            r = handle_event(_make_event(msg, ts, f"iac-{i}"), deps, f"iac-{i}")
            tools = [c.get("name") for c in r.proposal.tool_trace]
            print(f"\n  T{i} 👤 {msg}\n  T{i} 🏃 {r.reply}")
            print(f"      [type={r.proposal.type} action={r.policy.action} tools={tools or '-'} "
                  f"guard={'ok' if r.guard.ok else 'BLOCKED'}]")
            if not r.guard.ok:
                guard_all_ok = False
            with connect(db) as conn:
                weeks = conn.execute("select count(*) c from v0_planned_weeks where user_id = 1").fetchone()["c"]
            if i == 2:
                committed_before_injury = weeks >= 1
            if i == 3:
                proposed = None
                if r.proposal.type == "week_proposal" and r.proposal.week_proposal is not None:
                    proposed = list(r.proposal.week_proposal.sessions)
                reproposed_no_intensity = proposed is not None and not _violations(proposed)
                if proposed is not None:
                    print("      proposed@T3: " + " | ".join(
                        f"{s.get('date','?')[-5:]} {s.get('type','?')} {s.get('intensity','?')}" for s in proposed))

        ok = committed_before_injury and reproposed_no_intensity and guard_all_ok
        print("\n  ── oracle (forced post-commit ordering) ──")
        print(f"   week committed before injury : {committed_before_injury}")
        print(f"   re-proposed no-intensity week : {reproposed_no_intensity}")
        print(f"   guard ok all turns            : {guard_all_ok}")
        print(f"\n  INJURY-AFTER-COMMIT: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        db.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
