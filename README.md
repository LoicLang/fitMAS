# FitMAS — a reliable LLM running coach

> An adaptive running coach you talk to in plain language. The bet: **the LLM understands and generates; a deterministic verifier holds authority.** Reliability comes from the checker, not from caging the model.

FitMAS is a personal engineering project about one hard problem in LLM products: **how do you make a conversational agent that mutates real state trustworthy enough to use every day — without drowning it in rules?**

It is built as an antidote to the failure mode that killed its own predecessor.

---

## The failure mode this refuses

The earlier version of this app died of **deterministic fix-on-fix**: every broken case got one more rule (a regex, a keyword, a template, a branch). Those rules are invisible in tests (you only test the cases you imagined) and lethal in production (the case you didn't). The result is the classic trap:

> **perfect in test, incapable in reality.**

So the rebuild (`runtime_v0/`) inverts the responsibility split:

| Concern | Owner |
|---|---|
| Understanding free user text | **LLM** (never a regex / keyword) |
| Generating a plan / personalizing | **LLM** |
| Validating, authorizing, committing, auditing | **Deterministic backend** |
| Holding authority on safety & structure | **Deterministic verifier + policy** |

The principle, applied to planning: **verifying is easier than generating — so determinism lives on the tractable side.** The LLM proposes a training week; a deterministic verifier judges it against a handful of safety/structure properties (load progression, no unexplained drop, key-session type, no session on a day the athlete is away, no hard work on an injury). Nothing the LLM says about the user's text is parsed by a rule. Nothing is written to the DB except through one audited executor. No visible reply is allowed to claim a write that didn't happen.

---

## The loop

```
InputEvent → WorldSnapshot → CoachAgent → ActionProposal → RuntimePolicy
          → CommandExecutor → RuntimeResult → ReplyComposer → OutputGuard → Audit
```

- **WorldSnapshot** — a read-only photo of the user (plan, recent training, active facts, pending) handed to the model. The model never queries the DB directly.
- **CoachAgent** — the LLM, in a bounded ReAct loop, reads via read-tools and emits a typed `ActionProposal` (never raw text that gets parsed).
- **RuntimePolicy** — the authority. Grounds the proposal against DB truth, decides allow / pending / block, and compiles typed commands.
- **CommandExecutor** — the only writer. Transactional, idempotent per event, every mutation emits an audit event.
- **OutputGuard** — reads the *model's own output* and blocks a reply that lies about a write, leaks internals, or claims a non-existent action.

The sport engine is a **coach-callable toolbox** (`propose_week`) in the same tool-calling paradigm: high-level intent → deterministic engine → typed proposal → policy gate. The LLM places the easy runs and writes the prose; the verifier owns the numbers and the prescribed key session.

---

## How reliability is actually proven

The discipline is that **a green test number is never the bar.** A scripted matrix tunes both sides of the exchange — so it can only ever be an anti-regression / danger net, never a quality compass. Quality is judged on an **unscripted turn**.

**Two layers:**

1. **Mechanical matrix** (`scripts/v0_eval/run_matrix.py`) — anti-regression + danger metrics across scenarios and providers. A change must not regress it and must keep danger metrics at zero (`wrong_write`, `old_plan`, `claim_without_event`, …).
2. **Live subagent simulation** (`scripts/v0_eval/probe_live_simulation.py`) — an LLM role-plays an unscripted athlete (an injury, a work trip, boredom) against the *real* coach loop on a real provider. Deterministic oracles guarantee safety (guard ok every turn, no auto-commit, no constraint breach); an LLM judge scores quality. A change is "done" only when it survives a real turn here.

**Current proof (offline):** 262 tests pass, fake matrix 11/11, danger metrics 0, output-guard fallback 0%.

**Current proof (live, DeepSeek, unscripted):** two adaptation capabilities hold end-to-end —

- *Injury* — "looks good, but my knee hurts since yesterday" → the coach notes the constraint **and re-proposes a no-intensity week in the same turn**, presented for confirmation. Judge 5/5/5/5.
- *Availability* — "I'm away Wed–Thu, can you make it still work?" → the coach re-plans around the blocked days (rest on Wed/Thu, compensates elsewhere), same turn. Judge 5/5/5/5.

Crucially, the design **fails safe**: where the predecessor would commit a hard week under a fresh injury, V0 holds.

---

## What it does today (V0 dogfood scope)

Plan a running week, adjust it as life happens, see it:

- propose / commit a week (always behind a confirmation — the engine never auto-commits a plan)
- re-adapt **same-turn** under an injury (no-intensity week) or an availability window (rest on blocked days)
- read back the committed week
- block sport-unsafe mutations; an output guard that won't let a reply lie

**Deliberately out of scope (for now):** execution tracking against the plan, long-term periodization, multi-sport, nutrition, a heartbeat that mutates state. Running-only first — because load is verifiable by hand, and you can't prove reliability you can't check.

---

## Reading the repo

This repo is built to explain itself. Start here:

1. [`AGENTS.md`](AGENTS.md) — the doctrine and working agreement (the north star, the hard rules).
2. [`PROJECT.md`](PROJECT.md) — current status and proof.
3. [`docs/`](docs/) — `RUNTIME-V0.md` (core reference), `V0-CODE-MAP.md` (file-by-file), `PLANNING-V0.md` (the LLM/verifier split), `V0-TEST-DOCTRINE.md` (the two layers), `LLM-FIRST-CONVERSATION.md` (the user-text rule).
4. `backend/src/fitmas/runtime_v0/` — the proven core (isolated; it imports no legacy module).

Design specs and implementation plans for each shipped slice live under [`docs/superpowers/`](docs/superpowers/).

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

## Status & honesty

This is an in-progress prototype, not a finished product. The V0 conversational core and the running week engine are proven offline and on live unscripted simulation; the next steps are real Telegram dogfooding and strangling the remaining legacy pipeline behind proven adapters. The architecture decision is explicit: **the repo is the product envelope, `runtime_v0/` is the proven target core, the old pipeline is legacy to strangle** — no big-bang rewrite.

Stack: FastAPI · SQLite · SQLAlchemy 2.0 · python-telegram-bot · OpenAI-compatible providers (DeepSeek primary) · React/Vite webapp.

Personal project by Loïc Lang. Source-available for review.
