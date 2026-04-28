Loïc owns this, 

Start every session: say hi + one motivating line, only on the first sessions message 

Work style: telegraph. Short phrases. Minimal tokens. Drop filler.


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

- We are finishing **Phase A: reliable planning agent for real dogfood**.
- Do **not** open Phase B progression/prescription work unless Loic explicitly asks.
- Phase B long term = structured progression engine, prescription as source of truth, rendering after. It is documented but not the active build lane.
- Current Phase A next steps live in `docs/BUILD-ORDER.md`.

Core coach doctrine:

- LLM-first for fuzzy user intent.
- Determinism owns truth, validation, permissions, commit, audit.
- Determinism is a safety rail / last resort, not the coach brain.
- Regex and keywords are signal highlighters, never intent classifiers for fuzzy language.
- No helper should produce a final conversational reply unless it is outage, pending confirmation, or a summary of a real committed event.

Current action architecture:

- `CoachDecision` is the preferred decision contract.
- `PlanPatch` is the preferred planning action language.
- `PlanMutationService` is the writer for visible planning mutations.
- `validate_plan_patch` must run before commit.
- `requires_confirmation` stores the full `PlanPatch`, then revalidates before applying after explicit confirmation.
- Never expose a free write DB tool to the LLM.

Runtime tools / skill direction:

- Keep tools atomic and bounded.
- Multi-tool calls are expected; DeepSeek may request several tools in one turn.
- Every requested tool id must receive a result or explicit block.
- `suggest_replan_candidates` is the canonical candidate helper.
- `propose_replan` is legacy compat only.
- `replan_after_constraint` is a workflow in prompt/routing: read atomic tools -> optional candidate -> `PlanPatch | no_change | requires_confirmation`.

Provider reality:

- DeepSeek is the main provider path for cost/dogfood.
- Claude/Anthropic remains fallback where schema stability needs it.
- DeepSeek may still output prose after tool-use; JSON repair/fallback is expected, but never accept an invalid final decision silently.

Dogfood focus:

- Priority is a coach Loic can test all week on Telegram.
- Test real paths, not only unit tests:
  - "redonne le plan actuel"
  - "echange mardi et mercredi"
  - "je ne peux pas nager 2 semaines"
  - "j'ai fait X aujourd'hui"
  - short continuations: "oui", "running", "mercredi"
- Morning heartbeat has catch-up until 10h local if the jitter window was missed and no proactive message was sent.

High-risk regressions to avoid:

- Claiming a mutation happened without a committed `plan_mutation_event`.
- Treating `adapted` as proof that a session was done.
- Letting stale `session_description` drive the visible workout after sport/type replacement.
- Asking menus when tools are enough to decide.
- Reintroducing deterministic canned replies for availability, fatigue, pain, or short continuation turns.


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
- do not "solve" autonomy gaps by forcing deterministic paths when a prompt/tool/few-shot improvement can teach the model the right behavior
- determinism is a **safety rail** or **last resort**, never the long-term primary solution for coach reasoning
- regex / keyword heuristics must be treated as **signal highlighters**, not intent classifiers
- never create facts, mutate plans, or short-circuit coach reasoning from regex alone when user input is fuzzy (`douleur`, `soir`, `fatigue`, etc.)
- for fuzzy intent, inject detected signals into the LLM prompt with cautions about negation/context, let the LLM extract structured intent, then use deterministic code only for validation, permissions, safety rails, commit, and audit
- direct deterministic parsing is acceptable only for closed protocol replies with an active pending contract, e.g. explicit `oui/non` confirmation


# Tool / Skill Thinking (mandatory)

Before implementing a feature, ask:

1. Is this deterministic and reusable?  
   -> make it a **tool**.
2. Is this a multi-step workflow combining reasoning + several tools?  
   -> make it a **skill**.
3. Can this capability be reused by CLI + API + interactive chat?  
   -> centralize in a shared module.
4. Is user input fuzzy/approximate (typos, partial names, ambiguity)?  
   -> design tolerant matching + safe fallback/confirmation.
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
