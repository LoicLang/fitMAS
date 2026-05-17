---
summary: implementation plan for Decision Runtime Phase 8S canonical read-only default
read_when:
  - implementing Decision Runtime Phase 8S
  - default-enabling FITMAS_CANONICAL_READONLY_PROVIDER
  - debugging read-only turns that skip legacy CoachDecision
---

# Decision Runtime Phase 8S Canonical Read-Only Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the 8R canonical read-only provider path to default-on while keeping an explicit rollback flag.

**Architecture:** 8R creates the safe read-only path: `CoachUnderstanding -> DecisionOutcome(kind="answer") -> ReplyComposer`. 8S changes only the default of `FITMAS_CANONICAL_READONLY_PROVIDER` to on. Planning, pending, command lanes and close-turn remain outside this path.

**Tech Stack:** Python, pytest, existing Decision Runtime bridge and architecture tests.

---

## Scope

Default-enable:

```text
FITMAS_CANONICAL_READONLY_PROVIDER
```

Keep excluded:

```text
plan_change
requested_change
pending_response / active pending
memory/execution command signals
close_turn
```

## Tests

- `test_readonly_provider_flag_defaults_on_after_8s`
- `test_readonly_provider_can_be_disabled`
- `test_8s_readonly_provider_default_on_but_opt_out_supported`
- `scripts/smoke-decision-runtime-canonical-readonly`

## Acceptance

```text
Read-only truth turns skip legacy CoachDecision by default.
The env var can still opt out with FITMAS_CANONICAL_READONLY_PROVIDER=0.
No planning, pending, command or close-turn behavior changes.
```
