# Plan-Store Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Materialize a committed Meso week onto the day calendar (`v0_scheduled_sessions`) at commit time, so the two plan stores hold one truth — unblocking injury-after-commit, execution tracking, and surgical patching on a generated week.

**Architecture:** In `executor._apply_commit_week`, after inserting into `v0_planned_weeks`, also insert one `v0_scheduled_sessions` row per non-rest Meso session, in the same transaction. Replace `planned` rows in the week window; preserve executed ones. `planned_weeks` stays the provenance record; `scheduled_sessions` becomes the live truth.

**Tech Stack:** Python 3.12, SQLite (sqlite3), pytest. Live verification via `scripts/v0_eval/probe_live_simulation.py` (DeepSeek).

**Spec:** [`docs/superpowers/specs/2026-06-08-plan-store-reconciliation-design.md`](../specs/2026-06-08-plan-store-reconciliation-design.md)

**Branch:** `chore/repo-cleanup` (current). No push.

**Baseline:** `pytest tests/runtime_v0` = 262 passed. The README narrative rewrite is uncommitted in the working tree — leave it; `git add` only the files each task names.

**Confirmed mapping (Meso session → scheduled row):**
- `sport = "running"` (bootstrap convention; **Task 1 confirms** against `_session_to_dict`/existing rows)
- `title` = FR label from `type` (dict below)
- `intensity_label = session["intensity"]` (1:1 `easy`/`moderate`/`hard`)
- `priority = "key"` if `type == week.key_type` else `"secondary"`
- `status = "planned"`; `type == "rest"` → no row

---

## File Structure

- **Modify:** `backend/src/fitmas/runtime_v0/executor.py` — add `_materialize_week_sessions(...)` + call it in `_apply_commit_week`.
- **Create:** `tests/runtime_v0/test_executor_week_materialization.py` — Slice 1 deterministic tests.
- **Modify (Task 5):** whichever existing `tests/runtime_v0/*` assert an empty `current_plan` after a week commit — update expectations.

---

## Slice 1 — Materialize on commit (deterministic)

### Task 1: Confirm mapping vocab (read-only)

**Files:** none (investigation).

- [ ] **Step 1:** Read `_session_to_dict` (in `tools_read.py`) and one bootstrapped row path to confirm the `sport` string the reads expect and that `intensity_label` is the raw `easy/moderate/hard`.

Run: `grep -nE 'def _session_to_dict|sport|intensity_label' backend/src/fitmas/runtime_v0/tools_read.py | head`
Expected: confirms `sport` passthrough (use `"running"` unless reads clearly expect `"run"`), `intensity_label` raw string.

- [ ] **Step 2:** Confirm `executor.py` already imports `date`/`timedelta`/`json`.

Run: `grep -nE '^from datetime|^import json|from datetime import' backend/src/fitmas/runtime_v0/executor.py | head`
Expected: note what's imported; add `from datetime import date, timedelta` in Task 2 if missing.

### Task 2: Materialize helper + happy path

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/executor.py`
- Test: `tests/runtime_v0/test_executor_week_materialization.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/runtime_v0/test_executor_week_materialization.py
import json
import tempfile
from pathlib import Path

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.executor import _apply_commit_week


def _week_payload():
    return {
        "week_proposal": {
            "week_start": "2026-06-15",
            "source": "llm",
            "week_load": 370,
            "key_type": "threshold",
            "sessions": [
                {"date": "2026-06-15", "type": "rest", "duration_min": 0, "intensity": "easy"},
                {"date": "2026-06-16", "type": "threshold", "duration_min": 50, "intensity": "hard"},
                {"date": "2026-06-17", "type": "easy_run", "duration_min": 45, "intensity": "easy"},
                {"date": "2026-06-21", "type": "long_run", "duration_min": 80, "intensity": "moderate"},
            ],
        }
    }


def _rows(conn, user_id=1):
    return [dict(r) for r in conn.execute(
        "select date, sport, title, duration_min, intensity_label, priority, status "
        "from v0_scheduled_sessions where user_id = ? order by date", (user_id,)).fetchall()]


def test_commit_week_materializes_non_rest_sessions():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        with connect(db) as conn:
            _apply_commit_week(_week_payload(), conn, user_id=1)
            conn.commit()
            rows = _rows(conn)
        # rest day dropped -> 3 rows, not 4
        assert [r["date"] for r in rows] == ["2026-06-16", "2026-06-17", "2026-06-21"]
        thr = rows[0]
        assert thr["sport"] == "running"
        assert thr["intensity_label"] == "hard"
        assert thr["priority"] == "key"          # threshold == key_type
        assert thr["status"] == "planned"
        assert thr["title"]                        # non-empty label
        assert rows[1]["priority"] == "secondary"  # easy_run != key_type
    finally:
        db.unlink(missing_ok=True)
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor_week_materialization.py -q`
Expected: FAIL — `_apply_commit_week` doesn't insert into `v0_scheduled_sessions` yet (0 rows).

- [ ] **Step 3: Implement the helper + wire it in**

Add near the top of `executor.py` (after imports; add `from datetime import date, timedelta` if Task 1 Step 2 showed it missing):

```python
_MESO_TITLE = {
    "easy_run": "Footing facile",
    "long_run": "Sortie longue",
    "threshold": "Seuil",
    "intervals": "Intervalles",
    "recovery_run": "Récupération",
}


def _materialize_week_sessions(week: dict, connection, user_id: int) -> int:
    """Bridge a committed Meso week onto the day calendar.

    Replace `planned` rows in the week window; preserve executed ones; skip rest
    days and any day already settled. Returns the number of rows inserted.
    """
    week_start = date.fromisoformat(week["week_start"])
    week_end = week_start + timedelta(days=6)
    key_type = week.get("key_type")
    settled = {
        r["date"] for r in connection.execute(
            "select date from v0_scheduled_sessions "
            "where user_id = ? and date between ? and ? and status != 'planned'",
            (user_id, week_start.isoformat(), week_end.isoformat()),
        ).fetchall()
    }
    connection.execute(
        "delete from v0_scheduled_sessions "
        "where user_id = ? and date between ? and ? and status = 'planned'",
        (user_id, week_start.isoformat(), week_end.isoformat()),
    )
    inserted = 0
    for s in week["sessions"]:
        if s["type"] == "rest" or s["date"] in settled:
            continue
        connection.execute(
            "insert into v0_scheduled_sessions "
            "(user_id, date, sport, title, duration_min, intensity_label, priority, status) "
            "values (?, ?, ?, ?, ?, ?, ?, 'planned')",
            (
                user_id,
                s["date"],
                "running",
                _MESO_TITLE.get(s["type"], s["type"]),
                int(s["duration_min"]),
                s["intensity"],
                "key" if s["type"] == key_type else "secondary",
            ),
        )
        inserted += 1
    return inserted
```

Then in `_apply_commit_week`, after `row = connection.execute("select * from v0_planned_weeks where id = ?", (cursor.lastrowid,)).fetchone()`:

```python
    after = dict(row)
    after["materialized_sessions"] = _materialize_week_sessions(week, connection, user_id)
    return after
```

(Replace the existing `return dict(row)`.)

- [ ] **Step 4: Run it, expect PASS**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor_week_materialization.py -q`
Expected: PASS. (If `sport`/`intensity_label` mismatch a vocab the reads expect, adjust per Task 1 and re-run.)

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/executor.py tests/runtime_v0/test_executor_week_materialization.py
git commit -m "feat(meso): materialize committed week onto the day calendar"
```

### Task 3: Replace planned + preserve executed

**Files:**
- Test: `tests/runtime_v0/test_executor_week_materialization.py`

- [ ] **Step 1: Write the failing test**

```python
def test_recommit_replaces_planned_but_preserves_executed():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        with connect(db) as conn:
            # a stale planned row + an already-executed row in the week window
            conn.execute(
                "insert into v0_scheduled_sessions "
                "(user_id, date, sport, title, duration_min, intensity_label, priority, status) "
                "values (1,'2026-06-17','running','OLD',30,'easy','secondary','planned')")
            conn.execute(
                "insert into v0_scheduled_sessions "
                "(user_id, date, sport, title, duration_min, intensity_label, priority, status) "
                "values (1,'2026-06-16','running','DONE run',40,'easy','secondary','done')")
            _apply_commit_week(_week_payload(), conn, user_id=1)
            conn.commit()
            rows = _rows(conn)
        by_date = {r["date"]: r for r in rows}
        # stale planned 'OLD' on 06-17 replaced by the new easy_run
        assert by_date["2026-06-17"]["title"] != "OLD"
        # executed row on 06-16 preserved (NOT overwritten by the new threshold)
        assert by_date["2026-06-16"]["status"] == "done"
        assert by_date["2026-06-16"]["title"] == "DONE run"
        # no duplicate planned row added on the settled day
        assert sum(1 for r in rows if r["date"] == "2026-06-16") == 1
    finally:
        db.unlink(missing_ok=True)
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor_week_materialization.py -q`
Expected: PASS (the Task 2 helper already implements replace-planned + skip-settled). If it FAILS, fix the helper (do not weaken the test) and re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/runtime_v0/test_executor_week_materialization.py
git commit -m "test(meso): week materialization replaces planned, preserves executed"
```

### Task 4: Integration — get_current_plan shows the committed week

**Files:**
- Test: `tests/runtime_v0/test_executor_week_materialization.py`

- [ ] **Step 1: Write the failing test** (snapshot reads `v0_scheduled_sessions` for today..+14)

```python
def test_committed_week_visible_in_current_plan():
    from datetime import date as _date
    from fitmas.runtime_v0.snapshot import build_snapshot  # adjust import to the real builder
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db = Path(tmp.name)
    try:
        init_db(db)
        with connect(db) as conn:
            _apply_commit_week(_week_payload(), conn, user_id=1)
            conn.commit()
        snap = build_snapshot(db, user_id=1, today=_date(2026, 6, 14))
        dates = {s.date.isoformat() for s in snap.current_plan}
        assert "2026-06-16" in dates and "2026-06-21" in dates
        assert "2026-06-15" not in dates  # rest day not materialized
    finally:
        db.unlink(missing_ok=True)
```

- [ ] **Step 2: Run it** — Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor_week_materialization.py::test_committed_week_visible_in_current_plan -v`
Expected: PASS. If the snapshot builder name/signature differs, fix the import/call to the real one (check `snapshot.py`), not the assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/runtime_v0/test_executor_week_materialization.py
git commit -m "test(meso): committed week is visible in current_plan snapshot"
```

### Task 5: Fix blast radius + full gate

**Files:** whichever `tests/runtime_v0/*` now fail.

- [ ] **Step 1: Run the full suite, list failures**

Run: `.venv/bin/python -m pytest tests/runtime_v0 -q 2>&1 | tail -30`
Expected: some failures in tests that committed a week and asserted an empty/specific `current_plan`. Read each; the materialized week is now correct — update the expectation to match (do not revert the feature).

- [ ] **Step 2: Update the failing expectations** (one test at a time; re-run that test to green).

- [ ] **Step 3: Full gate**

```bash
.venv/bin/python -m pytest tests/runtime_v0 -q                 # all green
.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1 2>&1 | grep -A1 Failures   # No failures, danger 0
```
Expected: all green; matrix No failures.

- [ ] **Step 4: Commit**

```bash
git add tests/runtime_v0
git commit -m "test(meso): update plan-view expectations for materialized weeks"
```

---

## Slice 2 — Injury-after-commit proven on couche-2

### Task 6: Verify the live behavior (and only tweak the prompt if needed)

**Hypothesis:** Slice 1 makes the existing prompt rule (`coach_system.py` line 18: durable constraint + sessions touched → `propose_plan_patch`) actionable — the coach now sees the threshold session and can lighten it. Verify; only adjust the prompt if the path doesn't fire.

**Files:** possibly `backend/src/fitmas/runtime_v0/prompts/coach_system.py` (minimal, only if needed).

- [ ] **Step 1: Run the injury probe**

```bash
set -a && . ./.env && set +a
.venv/bin/python scripts/v0_eval/probe_live_simulation.py --provider deepseek --persona blessure
```
Expected: ideally `PERSONA BLESSURE: PASS` — the committed week's threshold gets lightened/replaced under the injury (no hard session in the active week), guard ok, no auto-commit. Run 2–3 times (live is flaky); read the transcript.

- [ ] **Step 2: If it does NOT fire** (coach still only records the fact), add one targeted line to `coach_system.py` near line 18, e.g.:

> `- Si une douleur/blessure est signalée alors qu'une semaine est déjà sur le calendrier avec une séance à intensité (seuil/intervalles/dur), allège-la ce tour-ci via propose_plan_patch(lighten, source_session_id=<lu via get_current_plan/get_session>), en plus de noter le fait. Ne laisse jamais une séance dure dans une semaine touchée par une blessure.`

Then re-run Step 1. Keep the change minimal; no regex on user text.

- [ ] **Step 3: Non-regression**

```bash
.venv/bin/python scripts/v0_eval/probe_live_simulation.py --provider deepseek --persona indispo   # still PASS
.venv/bin/python -m pytest tests/runtime_v0 -q                                                      # still green
.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1 2>&1 | grep -A1 Failures
```

- [ ] **Step 4: Commit** (only if the prompt changed)

```bash
git add backend/src/fitmas/runtime_v0/prompts/coach_system.py
git commit -m "fix(coach): lighten an intensity session in a committed week under a fresh injury"
```

- [ ] **Step 5: Capture the passing transcript** for the README "In action" block (the now-conclusive 2nd capability). Save the key turns (paraphrased/anonymized) for the repo finalization.

---

## Self-Review

**Spec coverage:** §1 bridge → Task 2 (wire into `_apply_commit_week`) ✓. §2 mapping → Task 1 (confirm) + Task 2 (helper) ✓. §3 replace/preserve → Task 3 ✓. §4 Slice 1 → Tasks 2–5; Slice 2 → Task 6 ✓. §5 blast radius → Task 5 ✓. §6 error handling: atomic via same-transaction insert in `_apply_commit_week` (commit/rollback owned by caller) ✓. Gate → Task 5 Step 3 + Task 6 Step 3 ✓.

**Placeholder scan:** No TBD/TODO. The one conditional (Task 6 Step 2 prompt tweak) is explicitly "only if the probe doesn't fire", with the exact line to add — not a placeholder. Vocab confirms (Task 1) have a stated default (`"running"`) and a fix rule.

**Type consistency:** `_materialize_week_sessions(week, connection, user_id)` signature consistent across Task 2 wiring + tests. `_apply_commit_week` returns `after` dict (now with `materialized_sessions`) — consistent with its existing `return dict(row)` contract (still a dict). Test helper `_week_payload()` / `_rows()` reused consistently across Tasks 2–4. Note: Task 2 Step 1 test calls `_apply_commit_week(_week_payload()["week_proposal"] and _week_payload(), ...)` — simplify to `_apply_commit_week(_week_payload(), conn, user_id=1)` (the function does `payload.get("week_proposal")`); fixed in Tasks 3–4 already.
