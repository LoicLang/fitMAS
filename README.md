# FitMAS — a reliable LLM running coach

[![CI](https://github.com/LoicLang/fitMAS/actions/workflows/ci.yml/badge.svg)](https://github.com/LoicLang/fitMAS/actions/workflows/ci.yml)

> An adaptive running coach you talk to in plain language. The bet: **the LLM understands and generates; a deterministic verifier holds authority.** Reliability comes from the checker — not from caging the model.

FitMAS is a personal engineering project, and an honest one: it is me working out, by trial and error, one hard problem in LLM products — **how do you make a conversational agent that mutates real state trustworthy enough to use every day, without drowning it in rules?** Most of what is here was *discovered by experiment*, not designed up front. What follows is the failure that started it, the bet that fixed it, and what each iteration taught me.

---

## What went wrong first

The first version died of **deterministic fix-on-fix**: every broken case got one more rule — a regex, a keyword, a template, a branch. Those rules are invisible in tests (you only test the cases you imagined) and lethal in production (the case you didn't). The classic trap:

> **perfect in test, incapable in reality.**

It bloated, too: **234 files, 46,507 lines** of decision/planning logic that was rigid *and* unreliable. The lesson wasn't "write better rules" — it was that the architecture itself manufactured the rules.

---

## The bet

The rebuild (`runtime_v0/`) inverts who owns what:

| Concern | Owner |
|---|---|
| Understanding free user text | **LLM** — never a regex / keyword |
| Generating & personalizing a plan | **LLM** |
| Validating, committing, auditing | **Deterministic backend** |
| Authority over safety & structure | **Deterministic verifier + policy** |

The principle, applied to planning: **verifying is easier than generating — so determinism lives on the tractable side.** The LLM proposes a training week; a deterministic verifier judges it against a few safety/structure properties (load progression, no unexplained drop, key-session type, no session on a day the athlete is away, no hard work on an injury). No rule parses the user's text. Nothing reaches the DB except through one audited executor. No reply may claim a write that didn't happen.

---

## By the numbers

The small size is the *result* of getting the split right, not the premise:

| | Legacy (retired) | V0 (live core) |
|---|---:|---:|
| Files | 234 | **35** |
| Lines of Python | 46,507 | **5,015** |
| Systematic danger class (auto-commit) | present | **closed (6 → 0)** |

~**9× less code — and it fails safe where the old one failed dangerous.**

---

## The loop

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

---

## How I prove it — and how my testing had to change

My first instinct was a scripted test matrix. It went green — and lied. A scripted matrix tunes *both* sides of the exchange, so a high score only proves I imagined the right cases. That is the v1 trap, one level up. So the method itself had to evolve:

1. **Mechanical matrix** (`run_matrix.py`) — an anti-regression / danger net, never a quality compass. A change must not regress it and must keep danger metrics at zero (`wrong_write`, `old_plan`, `claim_without_event`, …).
2. **Live unscripted simulation** (`probe_live_simulation.py`) — an LLM role-plays an unscripted athlete (an injury, a work trip, boredom) against the *real* coach loop on a real provider. Deterministic oracles enforce safety; an LLM judge scores quality. **A change is "done" only when it survives a turn no one scripted.**

**Proof today** — offline: 265 tests, fake matrix 11/11, danger metrics 0, guard fallback 0%. And the live layer earned its keep the hard way: it once scored an injury turn **5/5/5/5 on the LLM judge while the deterministic oracle failed it** — the coach had noted a fresh injury but left a hard session in the already-committed week. The judge was fooled; the oracle was not. Root cause: two plan stores (the engine's planned week vs the live day calendar) were never reconciled, so a committed week was invisible to the coach. I fixed it (materialize the committed week onto the calendar; teach the coach to re-propose under a post-commit injury) and a forced-ordering probe now passes it (see **In action** below). Availability behaves the same — rest the blocked days, keep the key session. On a 90-run replay against the legacy app, V0 is **not yet better on raw usefulness** — and I say so — but the one systematic danger class is closed and `tie_bad` is 0. Honest write-up: [`docs/RUNTIME-V0-APP-COMPARISON.md`](docs/RUNTIME-V0-APP-COMPARISON.md).

---

## In action

A real, unscripted turn (DeepSeek; the coach is the live loop, operating in French — glossed here). The athlete commits a week, then reports an injury:

> **Athlete:** *"Plan my week, please."* → the coach proposes a week with a Tuesday **threshold** (hard) session.
> **Athlete:** *"Yes, lock it in."* → committed.
> **Athlete:** *"By the way — since yesterday my right calf hurts when I run."*
> **Coach:** *(reads the committed week, notes the injury)* *"Here's an adjusted week of the 15th — all easy running plus one moderate long run, no hard session, to respect the calf. Want me to set it?"* → behind confirmation, output guard clean.

Before the fix, on this exact ordering the coach only recorded the injury and left the hard session in the plan — the gap the LLM judge missed and the deterministic oracle caught. Now it re-plans safely. Reproduce: [`scripts/v0_eval/probe_injury_after_commit.py`](scripts/v0_eval/probe_injury_after_commit.py).

---

## What I learned

- **A deterministic generator accumulates rules you can't see.** They pass every test you wrote and fail the user you didn't imagine.
- **Verifying is easier than generating** — so put determinism on the verifier and let the LLM do the understanding it's actually good at.
- **A green number is not proof — not even an LLM judge's.** A scripted matrix measures your imagination; and an LLM quality judge happily scored a genuinely unsafe turn 5/5/5/5. Only a deterministic safety oracle reliably catches the dangerous case.
- **Bolt-on subsystems don't link themselves.** The planning engine and the live calendar grew as two stores; "committing" a week didn't put it on the calendar until I built the bridge. Design the seam in, or it *becomes* the bug.
- **"Fail safe" is designed, not hoped for** — a guard that reads the model's *own* output is the line between a wrong answer and a dangerous one.
- **Earn capability; don't assume it.** Running-only first, because load is verifiable by hand — you can't prove reliability you can't check.

---

## Where it is, and where it's going

**Live today (June 2026):** V0 is my daily Telegram coach, on its own audited store, having replaced the legacy bot. It plans a running week, adjusts it same-turn as life happens (injury, travel), reads it back, blocks unsafe mutations, and won't let a reply lie. This is early dogfood — honest gaps: the voice is terse, Strava activities aren't auto-matched to sessions yet, and proactive briefings are off.

**North star:** *the smallest reliable coach worth using every day* — then grow capability only once it's proven, one tool at a time (the line budget is a deliberate ratchet, not an accident).

**Next:** auto-match Strava activities to planned sessions (LLM-first) · warm up the reply voice · target the in-progress week, not just next Monday · grow the planning engine under the verifier (progression, then declared cycle transitions) · proactivity (morning brief, weekly review).

**Deliberately not yet:** multi-month periodization, multi-sport, nutrition, a heartbeat that auto-commits a mutation. The live next-step list is [`docs/BUILD-ORDER.md`](docs/BUILD-ORDER.md).

---

## Reading the repo

This repo is built to explain itself. Start here:

1. [`AGENTS.md`](AGENTS.md) — the doctrine and working agreement (the north star, the hard rules).
2. [`PROJECT.md`](PROJECT.md) — current status and proof.
3. [`docs/`](docs/) — `RUNTIME-V0.md` (core reference), `V0-CODE-MAP.md` (file-by-file), `PLANNING-V0.md` (the LLM/verifier split), `V0-TEST-DOCTRINE.md` (the two layers), `LLM-FIRST-CONVERSATION.md` (the user-text rule).
4. `backend/src/fitmas/runtime_v0/` — the proven core (isolated; imports no legacy module). Everything under `backend/src/fitmas/legacy/` is the **retired** pipeline, kept for provenance.

Design specs and implementation plans for each shipped slice live under [`docs/superpowers/`](docs/superpowers/) — the trail of how each piece was reasoned, built, and proven.

> Built and maintained with agentic coding tools (Claude Code + Codex) — the working doctrine lives in [`AGENTS.md`](AGENTS.md), which doubles as the Codex agents convention.

> Most docs are in French (this is a solo project); the code, tests, and this README are the entry points for an English reader.

---

## Quickstart

```bash
# install
python3 -m venv .venv && .venv/bin/python -m pip install -e .

# run the proven core test suite
.venv/bin/python -m pytest tests/runtime_v0

# mechanical matrix (no provider needed)
.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1

# live subagent simulation (needs a provider key in .env, e.g. DEEPSEEK_API_KEY)
.venv/bin/python scripts/v0_eval/probe_live_simulation.py --provider deepseek --persona all
```

**Dogfood it on Telegram** (runs locally, polls Telegram, no deploy):

```bash
set -a && . ./.env && set +a
export FITMAS_V0_DOGFOOD_CHAT_IDS="<your telegram chat id>"   # via @userinfobot
export FITMAS_V0_BOT_TOKEN="<a test bot token>"
.venv/bin/python scripts/dogfood_telegram.py
```

Then message it: *"plan my week"* → confirm → *"actually my knee hurts"* / *"I'm away Wed–Thu"*.

---

Stack: FastAPI · SQLite · SQLAlchemy 2.0 · python-telegram-bot · OpenAI-compatible providers (DeepSeek primary). The repo is the product envelope; `runtime_v0/` is the live core; the legacy pipeline is retired under `backend/src/fitmas/legacy/` — no big-bang rewrite.

Personal project by Loïc Lang. Source-available for review.
