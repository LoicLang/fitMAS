# AGENTS.md

How AI coding agents work inside FitMAS. Public on purpose: FitMAS is also an experiment in **agentic software development** — keeping AI-assisted work grounded in specs, tests, architecture constraints, runtime safety, and real dogfood feedback. **Single source of truth for agent doctrine, all tools** (`CLAUDE.md` is a short stub pointing here).

Working style: short and telegraphic, spec- and test-first. Start from the doctrine below before proposing work.


# North Star & Anti-Reactive Doctrine

The governing posture. It outranks any single fix. Re-read it before proposing work.

North star: **le plus petit coach Telegram fiable pour 1 a 2 semaines de dogfood** (`docs/BUILD-ORDER.md`).

The failure mode we refuse to repeat:

- The previous app died of deterministic **fix-on-fix**: every broken case got one more rule (regex / keyword / template / branch).
- Such rules are invisible in test (you only test cases you imagined) and lethal in real (the case you did not). Outcome: complexity creep + **"perfect in test, incapable in real"**.
- Judge every change against NOT repeating this. A fix that adds a deterministic branch on user text is suspect by default; prefer pushing the handling into the LLM.

V0's bet is the structural antidote: the LLM understands the text, the backend only validates / commits / audits, zero determinism on user text. It is built to **not accumulate rules**.

Unit of progress = **survives reality**, never a green number:

- Nothing is "done" on a scripted matrix score. The matrix scripts both sides of the exchange, so tuning to it recreates "perfect in test" through the back door. Use it ONLY as an anti-regression / danger net, never as a compass.
- A change is done when it holds on an **unscripted real turn**: live subagent simulation now (`docs/V0-TEST-DOCTRINE.md`, couche 2), real Telegram dogfood next.

Vision filter before coding — ask first:

- Does this serve a dogfood scenario, a safety metric, or an adapter toward real usage?
- If not, it is polish -> defer it.

Complexity ratchet stays down:

- Honor the V0 LOC budget (`docs/RUNTIME-V0.md`), keep the V0 core isolated, resist new deterministic branches.
- When friction repeats, simplify; do not pile on.


# Discussion Mode (CTO)

In discussion phases (brainstorm, planning, architecture):

- think and speak like a CTO
- challenge assumptions early
- surface trade-offs (speed, cost, complexity, reliability)
- prioritize scalable architecture decisions
- identify technical/product risks and mitigation paths
- propose phased delivery (MVP -> hardening -> scale)
- keep recommendations pragmatic and execution-oriented


# Agent Protocol

Primary context:

1. Chat history
2. PROJECT.md
3. docs/
4. source code

Use chat history for recent context.  
Use the repository for durable knowledge.


# FitMAS Essential Memory

Current durable direction:

- The active build is a **dogfoodable Product V0** around `backend/src/fitmas/runtime_v0/`. We are no longer finishing the legacy app.
- Architecture decision: the repo is the **product envelope**, `runtime_v0` is the **live core** (deployed prod 8 juin 2026), the old pipeline is **legacy — retired**. No new repo. The read-adapter (`materialize_v0_db`) was used one-shot to bootstrap the live store; the legacy bot is off. Legacy FastAPI/webapp still runs but its data is no longer the source of truth for the coach.
- Sources of truth: next steps `docs/BUILD-ORDER.md`; product scope `docs/V0-DOGFOOD-SCOPE.md`; core reference `docs/RUNTIME-V0.md`; internal code map `docs/V0-CODE-MAP.md` (how V0 works file-by-file); test method `docs/V0-TEST-DOCTRINE.md`; user-text doctrine `docs/LLM-FIRST-CONVERSATION.md`; planning engine architecture `docs/PLANNING-V0.md`.

V0 status (8 juin 2026, soir) — **LIVE PERSONAL DOGFOOD** (deployed, single-user, not production-grade):

- **V0 is Loïc's live Telegram coach as of evening 8 juin 2026.** `scripts/dogfood_telegram.py` runs in prod via `scripts/start-prod`, replacing the legacy bot. The legacy bot is retired; its scheduled jobs (Strava cron, morning briefing, weekly review) are off.
- **Live store**: `FITMAS_V0_DB_PATH` → `/data/fitmas_v0_dogfood.db` (Fly volume). V0 `v0_*` tables = source of truth. Allowlist via `FITMAS_V0_DOGFOOD_CHAT_IDS` (Fly secret) = Loïc's Telegram chat id.
- **Bootstrapped from real data** (8 juin, `materialize_v0_db` in `runtime_v0/adapters/current_db_snapshot.py`): current plan → `v0_scheduled_sessions`, activities → `v0_activities`, facts → `v0_facts`. Critical: `users.id=1` remapped to `telegram_chat_id`; legacy future plan dropped (V0 plans the future itself); legacy junk facts dropped (literal "9.3", duplicates, meta-coach instructions — exactly the rule/fact accumulation V0 is built to avoid).
- **Strava → V0 sync LIVE**: `runtime_v0/adapters/strava_v0_sync.py` (`sync_strava_to_v0`) pulls recent Strava activities via legacy token, upserts into `v0_activities` de-duped by Strava activity id. Periodic job in runner (`FITMAS_V0_STRAVA_SYNC_SECONDS`, default 900 s). Verified live (HTTP 200, ~100 activities synced).
- Core proven: 265 tests pass, fake matrix 11/11, danger metrics 0, guard fallback 0 %, core ~4496 LOC (cap 4496). Budget **re-baselined** (7 juin): the Meso engine + the plan-store bridge are a deliberate **earned envelope**, not creep; ~2500 stays the ratchet for the bare conversational loop. See `docs/RUNTIME-V0.md` Budget.
- Proven couche 2 (DeepSeek): propose→confirm→commit + reject; constrained-week 4/4; injury same-turn re-adaptation PASS (LLM judge 5/5/5/5); availability same-turn re-adaptation PASS (REST on blocked days, LLM judge 5/5/5/5); **injury-after-commit re-adaptation PASS** (forced-ordering probe 2/2, after the two-store reconciliation — coach re-proposes a no-intensity week when a fresh injury hits an already-committed week). Live multi-turn self-play fails **safe** where the legacy app committed a hard week under injury.
- **Known gaps (not bugs — next tranches)**: run↔session not auto-matched (coach sees activities, can mark done on user request, no auto-mark from Strava sync); reply voice is terse; `propose_week` targets next Monday only; proactivity (briefings, weekly review) is off; solo only (Strava sync hardcodes `legacy_user=1`).
- Provider matrix: 11 scenarios x 3 providers (DeepSeek main, + Mistral, Grok; Gemini opt-in). Re-run for fresh numbers; exports not committed.

Proof bar (current milestone):

- **Bar cleared for live dogfood**: V0 is live on real data. Potential shown AND verified on real unscripted simulation. The bar now is: **sustain reliability on real dogfood** — track failure profile on real turns, fix safe, never accumulate deterministic rules.
- "Better" remains failure-profile-first: V0 must fail **safe** where the app failed **dangerous**. Never game a raw rate.

Test doctrine (`docs/V0-TEST-DOCTRINE.md`), two layers:

- Couche 1 — matrix = mechanical regression / danger net. NOT a quality compass.
- Couche 2 — live subagent simulation = where real quality and the app comparison are judged. A change is "done" only when it survives an unscripted real turn.

V0 loop:

`InputEvent -> WorldSnapshot -> CoachAgent -> ActionProposal -> RuntimePolicy -> CommandExecutor -> RuntimeResult -> ReplyComposer -> OutputGuard -> Audit`

V0 product scope (`docs/V0-DOGFOOD-SCOPE.md`):

- plan now / today / tomorrow; execution done / skipped / partial; execution correction; simple move / lighten / replace in place (auto-commit if the target is clear); pending for a key session, a swap, or a multi-operation; block for clear sport risk; heartbeat read-only or short question only.

Out of scope — do not open without an explicit ask:

- Phase B progression / prescription, full long-term replan, multi-month periodization, nutrition, multi-agent, vector / reflexive memory, a heartbeat that auto-commits a mutation, complex decision UI.

Sport engine <-> runtime co-evolution (`docs/PLANNING-V0.md`):

- Build the sport planning engine and the runtime **together, intertwined** — never two separate tracks bolted together later, or they will never link cleanly. The engine is a **coach-callable toolbox** (high-level intent -> deterministic engine -> typed proposal -> policy gate), same tool-calling paradigm as the runtime. Grow one tool at a time, each proven on couche 2.
- Planning principle: **the LLM generates and personalizes; a deterministic verifier holds authority.** Reliability comes from the verifier, not from constraining the LLM. This extends the user-text rule to plan generation: determinism is verification / validation / commit / audit, **never** understanding or imposed generation (verifying is easier than generating — keep determinism on the tractable side). This is the opposite of the legacy app (a deterministic generator with the LLM in a narrow role), which is exactly why the app is rigid/buggy.
- Coherence (progression, long-term arc) is carried by **context management** — a hierarchical context-pack (block intent + last-week actuals + constraints + signals), not by a deterministic generator. The LLM never manages the long term (its documented weakness).
- The verifier is **bi-mode**: continuity (smooth progression within a cycle) vs transition (a declared, justified cycle break — allow the discontinuity, enforce safety, always pending). The LLM's declared intent selects the mode. The key session type/progression is prescribed, not LLM free choice; the verifier rejects type-drift even at equal load.
- **Running-only first** (load verifiable by hand). The exact LLM/deterministic cut is **discovered empirically** — start ~100% LLM + a minimal safety verifier; determinism only grows on proof of drift. The legacy planning engine is **to strangle, not to bridge** (buggy / over-built). Open questions are tracked in `docs/PLANNING-V0.md`.

Next tranche (`docs/BUILD-ORDER.md`):

1. ~~Make "oui mais [constraint]" re-propose at turn N+1 for injury~~ — **DONE (couche 2 proven, 8 juin)**. Same-turn re-adaptation shipped.
2. ~~**Type availability** as a constraint so the coach can re-plan around blocked days~~ — **DONE (couche 2 proven, 8 juin)**. `blocked_days` declared, REST on blocked days, LLM judge 5/5/5/5.
3. ~~**Deploy V0 live in prod**~~ — **DONE (8 juin, soir)**. Runner replaces legacy bot, store bootstrapped from real data (materialize + user_id remap + junk-facts drop), Strava→V0 sync live (900 s, verified).
4. **Run↔session matching** (LLM-first: teach coach to mark done from a clearly matching Strava activity; full auto-proactive needs heartbeat — deferred).
5. **Voice tuning** — warm up terse list replies.
6. **`propose_week` "this week" param** — target the in-progress week, not only next Monday.
7. **Cross-turn availability persistence** (store typed blocked-days on the fact).
8. **Modify / preference path** ("make it more varied").
9. **Heartbeat / proactivity** (briefings, weekly review, auto-reconcile — what the legacy bot did, V0 will own).

Hard rules:

- The LLM understands user text and emits structured artifacts; the backend validates, authorizes, commits, audits. (Guarding the model's OWN output is allowed — that is `guard.py`.)
- No regex / keyword on free user text. No DB write outside the official executor / writer. No visible reply may lie about a write (danger metric `claim_without_event`).
- `runtime_v0` stays isolated — it must not import `fitmas.decision` / `domain` / `llm` / `skills` / `tools` / `app` — until the adapters are proven.


# Workflow

Before coding:

1. read the latest messages in the conversation
2. run `./scripts/docs:list`
3. read relevant docs
4. inspect related code


During implementation:

- small incremental changes
- follow existing patterns
- keep files readable
- avoid unnecessary abstractions


# Architecture Guardrails

For long-term evolvability:

- keep **domain modules** pure when possible
- a domain function should preferably **return a draft / decision / payload**, not send network calls directly
- **delivery and persistence happen in orchestrators** (`api.py`, bot schedulers, command handlers) after success
- do not hide cross-boundary side effects inside scoring / planning / heartbeat logic
- avoid growing hotspot files forever; when a file becomes multi-purpose, split by bounded context
- shared concerns must live in shared modules:
  - time / timezone / recency
  - channel delivery
  - message persistence
  - signal derivation
- debug endpoints and admin surfaces must be **disabled by default in production** unless explicitly enabled
- do not "solve" autonomy gaps by forcing deterministic paths; the LLM must understand the user and emit structured actions
- determinism is validation / permissions / commit / audit on LLM-produced or DB-produced artifacts, never user-text understanding
- regex / keyword heuristics on free user text are forbidden in conversation runtime, including as prompt highlighters
- never create facts, mutate plans, resolve pending confirmations, choose tools, or short-circuit coach reasoning from regex or keywords on user input
- pending confirmation replies (`oui`, `non`, "oui mais...") must be interpreted by the LLM in context through a structured `pending_resolution`


# Tool / Skill Thinking (mandatory)

Before implementing a feature, ask:

1. Is this deterministic and reusable?  
   -> make it a **tool**.
2. Is this a multi-step workflow combining reasoning + several tools?  
   -> make it a **skill**.
3. Can this capability be reused by CLI + API + interactive chat?  
   -> centralize in a shared module.
4. Is user input fuzzy/approximate (typos, partial names, ambiguity)?  
   -> make the LLM extract typed intent/references first; deterministic matching only resolves those typed references against DB truth.
5. What will be needed later for cloud execution?  
   -> avoid local-only assumptions in interfaces.

Agents must proactively propose tool/skill decomposition to make the agent more capable over time.


After implementing:

- verify behavior
- run tests if available
- update docs if behavior changed


# Proactive Quality Loop (mandatory)

Agents must be proactive on reliability:

- regularly run real CLI flows (not only unit tests) to catch integration issues early
- reproduce likely user paths and edge cases in terminal mode
- if a bug is found: fix, refactor, and re-run the same scenario until stable
- optimize and simplify code when repeated friction is observed
- report what was tested concretely and what remains unverified

This proactive loop is required even when the user does not explicitly ask for tests.


# Documentation

Docs live in `docs/`.

Each document must contain front matter:

---
summary: short description
read_when:
  - situations when this doc should be read
---

Example:

---
summary: tool system architecture
read_when:
  - adding a tool
  - modifying tool execution
---

Agents should read relevant documentation before modifying code.


# Code Style

Prefer simple code.

Rules:

- clarity over cleverness
- small functions
- readable naming
- consistent patterns

Avoid unnecessary complexity.


# Git Safety

Safe commands:

git status  
git diff  
git log

Forbidden without explicit instruction:

git reset --hard  
git clean  
deleting files


Commits:

- small
- clear message
- logical change


# Repository Philosophy

Chat history = short-term context  
Repository = long-term memory

The project should be understandable by reading:

PROJECT.md  
docs/  
source code


# Objective

Maintain a **self-explaining repository**.

A new agent should understand the system quickly by reading the repo and recent conversation.

<frontend_aesthetics> Avoid “AI slop” UI. Be opinionated + distinctive.

Do:

Typography: pick a real font; avoid Inter/Roboto/Arial/system defaults.
Theme: commit to a palette; use CSS vars; bold accents > timid gradients.
Motion: 1–2 high-impact moments (staggered reveal beats random micro-anim).
Background: add depth (gradients/patterns), not flat default.
Avoid: purple-on-white clichés, generic component grids, predictable layouts. </frontend_aesthetics>
