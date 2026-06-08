# FitMAS

**An adaptive running coach you talk to in plain language — and a study in shipping an LLM agent you can trust.**

[![CI](https://github.com/LoicLang/fitMAS/actions/workflows/ci.yml/badge.svg)](https://github.com/LoicLang/fitMAS/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)

> **The bet:** the LLM understands and generates; a deterministic verifier holds authority. Reliability comes from the checker — not from caging the model.

---

## Why I built it

Real life breaks training plans. You get a calf niggle, a work trip, a flat week — and generic trackers just plow ahead with the idealized plan. I wanted a coach you *talk to*, in plain language, that adapts to what actually happened.

The first version I built died of **deterministic fix-on-fix**: every broken case got one more rule — a regex, a keyword, a template, a branch. Those rules pass every test you wrote and fail the user you didn't imagine. The classic trap:

> **perfect in test, incapable in reality.**

So I rebuilt it (`runtime_v0/`) around one bet: **let the LLM understand and generate; let a deterministic verifier hold authority over safety and structure.** This repo is me working that out by trial and error — most of what's here was discovered by experiment, not designed up front.

## In action

A real, unscripted turn (DeepSeek; the coach is the live loop, operating in French — glossed here). The athlete commits a week, then reports an injury:

> **Athlete:** *"Plan my week, please."* → the coach proposes a week with a Tuesday **threshold** (hard) session.
> **Athlete:** *"Yes, lock it in."* → committed.
> **Athlete:** *"By the way — since yesterday my right calf hurts when I run."*
> **Coach:** *(reads the committed week, notes the injury)* *"Here's an adjusted week of the 15th — all easy running plus one moderate long run, no hard session, to respect the calf. Want me to set it?"* → behind confirmation, output guard clean.

Before the fix, on this exact ordering the coach only recorded the injury and left the hard session in the plan — a gap the LLM judge scored 5/5/5/5 and the deterministic oracle caught. Now it re-plans safely. Reproduce: [`scripts/v0_eval/probe_injury_after_commit.py`](scripts/v0_eval/probe_injury_after_commit.py).

## What it does

- Plan a running week — always behind a confirmation; the engine never auto-commits a plan.
- Adapt it **same-turn** as life happens: an injury → a no-intensity week; a work trip → rest the blocked days and keep the key session.
- **Re-adapt a week you've already committed** when a fresh injury lands.
- Read the committed week back; block sport-unsafe mutations.
- An output guard that won't let a reply lie about a write.

## How it works

```
InputEvent → WorldSnapshot → CoachAgent → ActionProposal → RuntimePolicy
          → CommandExecutor → RuntimeResult → ReplyComposer → OutputGuard → Audit
```

- **WorldSnapshot** — a read-only photo of the user handed to the model; it never queries the DB.
- **CoachAgent** — the LLM in a bounded ReAct loop; emits a typed `ActionProposal`, never raw text to be parsed.
- **RuntimePolicy** — the authority: grounds the proposal against DB truth, decides allow / pending / block, compiles typed commands.
- **CommandExecutor** — the only writer; transactional, idempotent per event, every mutation audited.
- **OutputGuard** — reads the *model's own reply* and blocks anything that lies about a write or claims a non-existent action.

The sport engine is a coach-callable tool (`propose_week`): high-level intent → deterministic engine → typed proposal → policy gate. The LLM places the easy runs and writes the prose; the verifier owns the numbers and the prescribed key session.

## Design decisions

- **The LLM understands; the verifier decides.** Free user text is never parsed by a rule. The LLM proposes a week; a deterministic verifier judges it against a few safety/structure properties (load progression, no unexplained drop, prescribed key-session type, no session on a day the athlete is away, no hard work on an injury). *Verifying is easier than generating — so determinism lives on the tractable side.*
- **One audited writer + a guard on the model's own output.** Nothing reaches the DB except through one transactional executor, and no reply may claim a write that didn't happen (`claim_without_event`). "Fail safe" is designed, not hoped for.
- **One plan, not two.** The planning engine and the live day calendar started as separate stores; "committing" a generated week didn't actually put it on the calendar — so the coach couldn't see or adapt a committed week. The seam *was* the bug (it's what produced the failure in **In action**). Committing now materializes the week onto the calendar (replace planned, preserve executed), so reads, edits, and execution share one truth.
- **The test method had to evolve.** My first instinct was a scripted matrix; it went green and lied (a scripted matrix tunes *both* sides, so a high score only proves I imagined the right cases). It now serves as a danger net, never a quality compass — quality is judged on an unscripted turn (see *How I prove it*).

## By the numbers

The small live core is the *result* of getting the split right, not the premise:

| | Legacy (retired) | V0 (live core) |
|---|---:|---:|
| Files | 234 | **35** |
| Lines of Python | 46,507 | **5,015** |
| Systematic danger class (auto-commit) | present | **closed (6 → 0)** |

~**9× less code — and it fails safe where the old one failed dangerous.**

## How I prove it

Two layers, by design:

1. **Mechanical matrix** (`scripts/v0_eval/run_matrix.py`) — anti-regression + danger metrics across scenarios and providers; offline, deterministic. A change must keep danger metrics at zero.
2. **Live unscripted simulation** (`scripts/v0_eval/probe_live_simulation.py`) — an LLM role-plays an unscripted athlete (an injury, a work trip, boredom) against the *real* coach loop on a real provider. Deterministic oracles enforce safety; an LLM judge scores quality. **A change is "done" only when it survives a turn no one scripted.**

Proof today: 265 tests, fake matrix 11/11, danger metrics 0, output-guard fallback 0%. The live layer earned its keep the hard way — it once scored an injury turn **5/5/5/5 on the LLM judge while the deterministic oracle failed it** (the coach left a hard session in an already-committed week). The judge was fooled; the oracle was not. That bug is now fixed and proven by a forced-ordering probe. On a 90-run replay against the legacy app, V0 is **not yet better on raw usefulness** — and I say so — but the one systematic danger class is closed and `tie_bad` is 0. Honest write-up: [`docs/RUNTIME-V0-APP-COMPARISON.md`](docs/RUNTIME-V0-APP-COMPARISON.md).

## Tech stack

Python 3.12 · FastAPI · SQLite · SQLAlchemy 2.0 · python-telegram-bot · OpenAI-compatible providers (DeepSeek primary) · React/Vite (legacy webapp). Built and maintained with agentic coding tools (Claude Code + Codex) — the working doctrine lives in [`AGENTS.md`](AGENTS.md), which doubles as the Codex agents convention.

## Getting started

```bash
# install
python3 -m venv .venv && .venv/bin/python -m pip install -e .

# dogfood it on Telegram (runs locally, polls Telegram, no deploy)
set -a && . ./.env && set +a
export FITMAS_V0_DOGFOOD_CHAT_IDS="<your telegram chat id>"   # via @userinfobot
export FITMAS_V0_BOT_TOKEN="<a test bot token>"
.venv/bin/python scripts/dogfood_telegram.py
```

Then message it: *"plan my week"* → confirm → *"actually my knee hurts"* / *"I'm away Wed–Thu"*.

## Running the tests

```bash
# the proven core suite
.venv/bin/python -m pytest tests/runtime_v0

# mechanical matrix (no provider key needed)
.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1

# live subagent simulation (needs a provider key in .env, e.g. DEEPSEEK_API_KEY)
.venv/bin/python scripts/v0_eval/probe_live_simulation.py --provider deepseek --persona all
```

## Project layout

```
backend/src/fitmas/
  runtime_v0/        the live core — the proven, isolated coach loop (imports no legacy module)
    meso/            the running-week engine (LLM generates → deterministic verifier)
    adapters/        bridges to live data (Strava sync, snapshot bootstrap)
  legacy/            the retired pre-rebuild pipeline, kept for provenance only
docs/                doctrine + design specs + the V0-vs-legacy comparison
  superpowers/       the spec → plan trail for each shipped slice
scripts/v0_eval/     the evals: mechanical matrix + live subagent probes
tests/runtime_v0/    the proven-core test suite
frontend/            legacy React webapp (still served, but no longer the source of truth)
```

## Status & limitations

As of June 2026, **V0 is live in production** — it is my daily Telegram coach, on its own audited store, having replaced the legacy bot. This is early dogfood, not a finished product. Honest gaps: the reply voice is terse, Strava activities aren't auto-matched to planned sessions yet, and proactive briefings are off. The architecture decision is explicit: the repo is the product envelope, `runtime_v0/` is the live core, and the old pipeline is legacy — retired and quarantined under [`backend/src/fitmas/legacy/`](backend/src/fitmas/legacy/) — no big-bang rewrite.

## Roadmap

The north star is *the smallest reliable coach worth using every day* — then grow capability only once it's proven, one tool at a time (the line budget is a deliberate ratchet). Next: auto-match Strava activities to planned sessions (LLM-first) · warm up the reply voice · target the in-progress week, not just next Monday · grow the planning engine under the verifier (progression, then declared cycle transitions) · proactivity (morning brief, weekly review). Deliberately not yet: multi-month periodization, multi-sport, nutrition, a heartbeat that auto-commits. The live next-step list is [`docs/BUILD-ORDER.md`](docs/BUILD-ORDER.md).

## License

MIT — see [LICENSE](LICENSE). Personal project by Loïc Lang; source-available for review.
