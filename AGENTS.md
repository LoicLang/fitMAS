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


# Workflow

Before coding:

1. read the latest messages in the conversation
2. run `docs:list`
3. read relevant docs
4. inspect related code


During implementation:

- small incremental changes
- follow existing patterns
- keep files readable
- avoid unnecessary abstractions


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
