---
summary: implementation plan for Decision Runtime Phase 8Y legacy delete gates
read_when:
  - implementing Decision Runtime Phase 8Y
  - preventing covered planning lanes from using legacy candidate fallback
  - preparing final legacy deletion after canonical coverage
---

# Decision Runtime Phase 8Y Legacy Delete Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete legacy authority for planning lanes already covered by the canonical provider by turning their legacy fallback into a hard regression.

**Architecture:** Do not delete broad legacy files while uncovered lanes still need them. Instead, make covered dogfood lanes non-negotiable: they must show canonical provider `handled`, `legacy_skipped=true`, and no active unclassified legacy fallback.

**Tech Stack:** Existing smoke evaluator and architecture tests.

**Status 2026-05-17:** delivered locally. Covered planning lanes now include `move_hard_close`, and the default-on wrapper hard-fails if they fall back to legacy.

---

### Task 1: Covered Planning Lanes Cannot Use Legacy

**Files:**
- Modify: `scripts/smoke_a_plus_api.py`
- Test: `tests/test_smoke_a_plus_api.py`

- [x] **Step 1: Expand required canonical scenario set**

Covered lanes:

```text
move_easy_then_confirm
swap_by_day
move_hard_close
```

- [x] **Step 2: Hard-fail non-canonical trace**

The smoke evaluator already fails missing canonical trace. Keep this as the delete gate for covered lanes.

### Task 2: Docs

**Files:**
- Modify: `docs/BUILD-ORDER.md`
- Modify: `docs/DECISION-RUNTIME-REFACTOR.md`
- Modify: `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`

- [x] **Step 1: Document 8Y honestly**

8Y does not delete every `legacy/` file. It deletes legacy authority for covered lanes and defines the final deletion criterion: no active `fallback_census` on dogfood lanes.

Delivered verification:

```bash
./scripts/smoke-decision-runtime-canonical-planning-default
# RESULT: OK (10 checks)

./scripts/test-backend -q
# 1376 passed, 11 skipped, 11 subtests passed

git diff --check
# OK
```
