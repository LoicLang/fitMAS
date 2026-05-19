---
summary: Phase 9D fallback census global and first empty legacy candidate route deletion
read_when:
  - continuing Decision Runtime legacy deletion after Phase 9C
  - reviewing fallback census reports
  - removing candidate or snapshot planning legacy paths
---

# Decision Runtime Phase 9D — Fallback Census And Candidate Delete

## Goal

Re-run a global fallback census over real smokes, classify remaining fallbacks by
owner, then delete only candidate legacy routes proven empty on covered lanes.

## Invariants

- No deterministic parsing of free user text.
- LLM Understanding may emit typed refs; backend may normalize typed machine
  refs only.
- No planning write outside the planning command/mutation path.
- No legacy candidate route may create a pending confirmation from an
  incomplete canonical requested change.
- Do not delete active legacy routes before the census identifies their owner
  and next migration step.

## Implemented Slice

1. Add `--fallback-census-json` to `scripts/smoke_a_plus_api.py`.
2. Remove the dead `availability_no_affected_session` candidate route from
   `conversation_pipeline.py`.
3. Block candidate/snapshot fallback when `CoachUnderstanding.requested_change`
   is low-confidence or missing required typed refs.
4. Normalize typed refs `session_id=3`, `session=3`, `id=3`.
5. Record `planning_snapshot_flow` in `fallback_census` so snapshot legacy is
   no longer invisible.
6. Add architecture/unit gates for the deletion and typed ref handling.

## Verification

```text
./scripts/test-backend -q
1405 passed, 11 skipped, 11 subtests passed

./scripts/smoke-a-plus-api --skip-generated-week --fallback-census-json .tmp-9d-core-fallback-census.json
RESULT: OK (15 check(s))

./scripts/smoke-a-plus-api --daily --skip-generated-week --fallback-census-json .tmp-9d-daily-fallback-census.json
RESULT: OK (26 check(s))
```

## Remaining Owners

- `planning_snapshot_flow`: still active for some create / broad constraint
  cases. Migrate these into canonical planning before deleting.
- `adaptation_candidate_flow`: now blocked on missing typed refs, but still
  present as a planning owner to remove after coverage improves.
- `legacy_decide`: still present on a few reply/read-only lanes, separate from
  planning deletion.
- `reply quality`: some canonical replies are artifact-safe but not polished.

