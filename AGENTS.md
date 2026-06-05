Loïc owns this, 

Start every session: say hi + one motivating line, only on the first sessions message 

Work style: telegraph. Short phrases. Minimal tokens. Drop filler.


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
- Architecture decision: the repo is the **product envelope**, `runtime_v0` is the **proven target core**, the old pipeline is **legacy to strangle**. No new repo, no big-bang Telegram migration, do not delete the old pipeline before adapters are proven.
- Sources of truth: next steps `docs/BUILD-ORDER.md`; product scope `docs/V0-DOGFOOD-SCOPE.md`; core reference `docs/RUNTIME-V0.md`; test method `docs/V0-TEST-DOCTRINE.md`; user-text doctrine `docs/LLM-FIRST-CONVERSATION.md`; planning engine architecture `docs/PLANNING-V0.md`.

V0 status (5 juin 2026):

- Core proven offline: 201 tests pass, fake matrix 11/11, danger metrics 0, guard fallback 0 %, core 3646 LOC (cap 3700, justified by the Meso engine; healthy target stays 2500 — watch the ratchet).
- Recently shipped: Meso sport engine (`runtime_v0/meso/` — typed week model + deterministic verifier with anti-TSS-drop, fact->TypedConstraint bridge), fact resolution (retract a healed health fact), fact rider (note a durable fact + act in one turn). Earlier: LLM-first visible voice, execution commit gated on the carrying fact, guard hardened.
- Provider matrix: 11 scenarios x 3 providers (DeepSeek main path, + Mistral, Grok; Gemini opt-in, no credit). DeepSeek may emit prose after tool-use; repair the artifact, never accept an invalid final decision silently. Re-run for a fresh number; exports are not committed.

Proof bar (current milestone):

- Potential is **shown**. The bar is now: **prove V0 better than the legacy app on real, unscripted simulation** (couche 2) — not on the scripted matrix, not on the legacy replay harness.
- "Better" keeps failure-profile-first: V0 must fail **safe** where the app fails **dangerous**, and at least match usefulness on the scenarios V0 covers. Never game a raw rate.

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

1. Re-run a targeted provider matrix on the 11 scenarios.
2. Build a `WorldSnapshot` from a copy of the current DB (distinguish faithful replay vs approximate debug).
3. Build an executor adapter to the existing writers.
4. Wire Telegram / API under a flag + user allowlist.

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
