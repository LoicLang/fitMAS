---
summary: Phase 9L plan for global fallback census after snapshot and candidate fallback deletion
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9K
  - auditing global fallback census reports
  - deciding which legacy modules can be moved or deleted
---

# Decision Runtime Phase 9L Global Census Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a repeatable global fallback census after deleting `planning_snapshot_flow` and `adaptation_candidate_flow`.

**Architecture:** 9L does not delete more runtime. It gathers evidence across smoke reports, classifies active fallback owners/sources, and separates runtime-active legacy from historical/pure modules. Deletion happens only after this census is readable and stable.

**Tech Stack:** Python script, smoke API JSON reports, pytest architecture tests, FitMAS fallback census.

---

## Tasks

- [x] Add tests for a reusable fallback census summary script.
- [x] Implement `scripts/decision-runtime-fallback-census-summary`.
- [x] Run core smoke with `--fallback-census-json`.
- [x] Run daily smoke with `--fallback-census-json`.
- [x] Combine both reports into one global summary.
- [x] Document owner/source counts and remaining module classification.
- [x] Run targeted tests, full backend, and `git diff --check`.

## Acceptance

- The summary script reports scenario counts, fallback scenario counts, owner counts and source counts.
- The script exits non-zero when fallback turns exist unless `--allow-fallbacks` is passed.
- The core and daily smoke reports can be combined without hand-editing.
- Docs say exactly what remains legacy after 9L.
