# Slice 2.1 — Meso Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Meso generator — the LLM emits a typed week from the `ContextPack`, a `generate→verify` loop judges it (Slice 1 verifier), with a deterministic template as a fallback after retries.

**Architecture:** LLM-first generation (template only as a fallback). The generator takes an injected `LLMClient`, calls it with a single `emit_week` tool whose args ARE the typed week, parses + verifies, feeds structured violations back on failure (max 3 attempts), then falls back to a deterministic standard week. Tier 2: an active intensity/all constraint relaxes the verifier's `load_drop` + key checks (constraint-aware anti-drop), driven by pack constraints (anti-gaming by construction). Running-only, continuity, everything pending. Offline only — runtime wiring is Slice 3.

**Tech Stack:** Python 3, dataclasses, pytest, `FakeLLMClient` for unit tests. Branch: `slice-2-1-generator`.

**Spec:** `docs/superpowers/specs/2026-06-06-slice-2-1-generator-design.md`

> **Note** — `generate_week` takes a `week_start: date` parameter (the Monday the week anchors on); sessions need real dates and the pack is date-free. This is a mechanical addition to the spec, consistent with it.
>
> **Commits** — atomic, one per task. CLAUDE.md: commits are pre-authorized for this plan (Loïc asked for atomic commits); proceed without re-asking.

---

## File Structure

- `backend/src/fitmas/runtime_v0/meso/verifier.py` — **Modify**: add public `limits_intensity()`; relax `load_drop` + key checks when it holds.
- `backend/src/fitmas/runtime_v0/prompts/week_generation.py` — **Create**: `GENERATION_SYSTEM` + `render_generation_prompt(pack, week_start, mode)`.
- `backend/src/fitmas/runtime_v0/meso/generator.py` — **Create**: `EMIT_WEEK_TOOL`, `_build_week`, `WeekProposal`, `generate_week`, `_template_week`.
- `tests/runtime_v0/test_meso_verifier.py` — **Modify**: relaxation tests.
- `tests/runtime_v0/test_meso_generator.py` — **Create**: parser, loop, fallback, cold-start tests.
- `scripts/v0_eval/generate_weeks.py` — **Create** (outside core): real-provider 4-6 week offline harness.

---

### Task 1: Constraint-aware relaxation in the verifier

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/meso/verifier.py`
- Test: `tests/runtime_v0/test_meso_verifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/runtime_v0/test_meso_verifier.py` (helpers `_s`, `_target` already exist):

```python
def test_active_intensity_constraint_relaxes_load_drop_and_key():
    # A low, key-less week is legitimate under an active intensity restriction:
    # load_drop + key checks are relaxed; nothing hard -> no health_conflict.
    target = _target(band=(300.0, 330.0), key_type="threshold")
    week = PlannedWeek(sessions=(_s(1, "easy_run", 30, "easy"), _s(3, "easy_run", 30, "easy")))
    constraint = TypedConstraint(severity="moderate", restricts=("intensity",), active=True)
    verdict = verify_week(week, target, (constraint,))
    assert verdict.ok
    assert verdict.requires_pending is True


def test_low_keyless_week_without_constraint_fails():
    target = _target(band=(300.0, 330.0), key_type="threshold")
    week = PlannedWeek(sessions=(_s(1, "easy_run", 30, "easy"), _s(3, "easy_run", 30, "easy")))
    verdict = verify_week(week, target)
    codes = {v.code for v in verdict.violations}
    assert "load_drop" in codes
    assert "key_session_count" in codes


def test_inactive_constraint_does_not_relax():
    target = _target(band=(300.0, 330.0), key_type="threshold")
    week = PlannedWeek(sessions=(_s(1, "easy_run", 30, "easy"),))
    constraint = TypedConstraint(severity="moderate", restricts=("intensity",), active=False)
    verdict = verify_week(week, target, (constraint,))
    assert "load_drop" in {v.code for v in verdict.violations}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_verifier.py -k "relax or keyless or inactive" -v`
Expected: FAIL — `test_active_intensity_constraint_relaxes_load_drop_and_key` fails (verdict not ok: load_drop + key_session_count still raised).

- [ ] **Step 3: Write minimal implementation**

In `backend/src/fitmas/runtime_v0/meso/verifier.py`, add this public helper after the imports (before `verify_week`):

```python
def limits_intensity(constraints: tuple[TypedConstraint, ...]) -> bool:
    """True if an active constraint forbids hard work (restricts intensity or all).

    Such a constraint materially limits the week: the load drop is *explained*, and a
    hard key session can't be prescribed. Driven by pack constraints (typed by the
    runtime at ingestion), not by the generator -> anti-gaming by construction.
    """
    return any(
        constraint.active and ({"intensity", "all"} & set(constraint.restricts))
        for constraint in constraints
    )
```

Replace `verify_week`'s continuity branch and `_check_load_continuity` signature:

```python
def verify_week(
    week: PlannedWeek,
    target: WeekTarget,
    constraints: tuple[TypedConstraint, ...] = (),
    mode: Mode = "continuity",
) -> WeekVerdict:
    violations: list[Violation] = []
    relaxed = limits_intensity(constraints)
    if mode == "continuity":
        if target.phase == "build" and not relaxed:
            violations.extend(_check_key(week, target))
        violations.extend(_check_load_continuity(week, target, drop_relaxed=relaxed))
    else:  # transition: discontinuity + type change allowed, safety enforced
        violations.extend(_check_load_transition(week, target))
    violations.extend(_check_spacing(week))
    violations.extend(_check_health(week, constraints))
    return WeekVerdict(
        ok=not violations,
        violations=tuple(violations),
        requires_pending=True,
    )
```

```python
def _check_load_continuity(
    week: PlannedWeek, target: WeekTarget, drop_relaxed: bool = False
) -> list[Violation]:
    low, high = target.load_band
    load = week.week_load
    out: list[Violation] = []
    if load < low and not drop_relaxed:
        out.append(
            Violation("load_drop", f"week load {load} below band min {low}", "high")
        )
    if load > high:
        out.append(
            Violation("load_spike", f"week load {load} above band max {high}", "medium")
        )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_verifier.py -v`
Expected: PASS (all, including the 3 new + the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/meso/verifier.py tests/runtime_v0/test_meso_verifier.py
git commit -m "feat(meso): constraint-aware relaxation (anti-drop + key) in verifier

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: The generation prompt

**Files:**
- Create: `backend/src/fitmas/runtime_v0/prompts/week_generation.py`
- Test: `tests/runtime_v0/test_meso_generator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/runtime_v0/test_meso_generator.py`:

```python
from __future__ import annotations

from datetime import date

from fitmas.runtime_v0.meso.model import (
    ContextPack,
    TypedConstraint,
    WeekActuals,
    derive_continuity_target,
)
from fitmas.runtime_v0.prompts.week_generation import (
    GENERATION_SYSTEM,
    render_generation_prompt,
)

MONDAY = date(2026, 6, 8)


def _pack(constraints=()):
    actuals = WeekActuals(total_load=300.0, key_type="threshold")
    return ContextPack(
        target=derive_continuity_target(actuals),
        last_week_actuals=actuals,
        constraints=constraints,
        signals=(),
    )


def test_generation_system_mentions_emit_tool():
    assert "emit_week" in GENERATION_SYSTEM


def test_render_prompt_includes_target_and_constraint():
    pack = _pack((TypedConstraint(severity="moderate", restricts=("intensity",), active=True),))
    text = render_generation_prompt(pack, MONDAY, "continuity")
    assert "threshold" in text          # prescribed key type
    assert "300.0" in text and "330.0" in text  # load band
    assert "2026-06-08" in text         # week start
    assert "intensity" in text          # active constraint surfaced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: ... prompts.week_generation`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/fitmas/runtime_v0/prompts/week_generation.py`:

```python
"""Prompt for the Meso week generator (Slice 2.1).

The LLM generates ONE running week as a typed skeleton via the emit_week tool. The
verifier judges numbers + enums; the free `detail` prose is the LLM's, never verified.
"""
from __future__ import annotations

from datetime import date, timedelta

from fitmas.runtime_v0.meso.model import ContextPack

GENERATION_SYSTEM = (
    "Tu es un coach de course a pied. Tu generes UNE semaine d'entrainement.\n"
    "Emets la semaine UNIQUEMENT via le tool emit_week (une liste de seances typees) — "
    "aucune prose libre en dehors du champ detail de chaque seance.\n"
    "Respecte la cible: garde le type de seance cle prescrit, vise la bande de charge, "
    "respecte les contraintes actives (pas d'intensite si l'intensite est restreinte).\n"
    "charge = duree_min x poids (easy=1.0, moderate=1.5, hard=2.0); rest = 0."
)


def render_generation_prompt(pack: ContextPack, week_start: date, mode: str) -> str:
    target = pack.target
    if target is None:
        raise ValueError("render_generation_prompt requires a target (continuity)")
    low, high = target.load_band
    end = week_start + timedelta(days=6)
    lines = [
        f"mode: {mode}",
        f"semaine: {week_start.isoformat()} -> {end.isoformat()} (lundi a dimanche)",
        f"phase: {target.phase}",
        f"seance cle prescrite: {target.key_type}",
        f"bande de charge: {low} a {high}",
        f"progression: {target.progression_axis}",
    ]
    if pack.last_week_actuals is not None:
        lines.append(
            f"semaine passee reelle: charge {pack.last_week_actuals.total_load}, "
            f"cle {pack.last_week_actuals.key_type}"
        )
    if pack.constraints:
        restrictions = sorted({r for c in pack.constraints if c.active for r in c.restricts})
        if restrictions:
            lines.append(f"contraintes actives: restreint {', '.join(restrictions)}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/prompts/week_generation.py tests/runtime_v0/test_meso_generator.py
git commit -m "feat(meso): week generation prompt (render ContextPack)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `emit_week` tool + `_build_week` parser

**Files:**
- Create: `backend/src/fitmas/runtime_v0/meso/generator.py`
- Test: `tests/runtime_v0/test_meso_generator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/runtime_v0/test_meso_generator.py` (add imports at top):

```python
import pytest

from fitmas.runtime_v0.meso.generator import EMIT_WEEK_TOOL, _build_week
from fitmas.runtime_v0.meso.model import PlannedWeek
```

```python
def test_build_week_parses_typed_sessions():
    week = _build_week(
        [
            {"date": "2026-06-09", "type": "threshold", "duration_min": 60, "intensity": "hard", "detail": "3x8"},
            {"date": "2026-06-13", "type": "easy_run", "duration_min": 40, "intensity": "easy"},
        ]
    )
    assert isinstance(week, PlannedWeek)
    assert week.week_load == 160.0  # 120 + 40
    assert week.sessions[0].type == "threshold"
    assert week.sessions[0].detail == "3x8"


def test_build_week_rejects_bad_type():
    with pytest.raises(ValueError):
        _build_week([{"date": "2026-06-09", "type": "sprint", "duration_min": 30, "intensity": "hard"}])


def test_build_week_rejects_bad_intensity():
    with pytest.raises(ValueError):
        _build_week([{"date": "2026-06-09", "type": "easy_run", "duration_min": 30, "intensity": "brutal"}])


def test_emit_week_tool_shape():
    assert EMIT_WEEK_TOOL.name == "emit_week"
    assert "sessions" in EMIT_WEEK_TOOL.parameters["properties"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -k "build_week or emit_week_tool" -v`
Expected: FAIL — `ModuleNotFoundError: ... meso.generator`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/src/fitmas/runtime_v0/meso/generator.py`:

```python
"""Meso week generator (Slice 2.1).

LLM-first: the LLM emits a typed week via the emit_week tool; a generate->verify loop
judges it; a deterministic template is the fallback. Calls an injected LLMClient (real
providers live in scripts/v0_eval/). Everything pending. See the Slice 2.1 design.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from typing import Any, Literal

from fitmas.runtime_v0.llm_clients.base import LLMClient, LLMResponse, ToolCall, ToolSchema
from fitmas.runtime_v0.meso.model import (
    ContextPack,
    PlannedWeek,
    TypedConstraint,
    TypedSession,
    WeekTarget,
)
from fitmas.runtime_v0.meso.verifier import Mode, WeekVerdict, limits_intensity, verify_week
from fitmas.runtime_v0.prompts.week_generation import GENERATION_SYSTEM, render_generation_prompt

_SESSION_TYPES = {"rest", "easy_run", "long_run", "threshold", "intervals", "recovery_run"}
_INTENSITIES = {"easy", "moderate", "hard"}


def _build_week(sessions: list[dict[str, Any]]) -> PlannedWeek:
    """Parse the LLM's emit_week args into a typed week. Raise ValueError on bad enums."""
    built: list[TypedSession] = []
    for raw in sessions:
        kind = raw.get("type")
        intensity = raw.get("intensity")
        if kind not in _SESSION_TYPES:
            raise ValueError(f"bad session type {kind!r}")
        if intensity not in _INTENSITIES:
            raise ValueError(f"bad intensity {intensity!r}")
        built.append(
            TypedSession(
                date=date.fromisoformat(raw["date"]),
                type=kind,
                duration_min=int(raw["duration_min"]),
                intensity=intensity,
                detail=raw.get("detail", ""),
            )
        )
    return PlannedWeek(sessions=tuple(built))


EMIT_WEEK_TOOL = ToolSchema(
    name="emit_week",
    description="Emit the planned running week as a list of typed sessions.",
    parameters={
        "type": "object",
        "properties": {
            "sessions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "format": "date"},
                        "type": {"type": "string", "enum": sorted(_SESSION_TYPES)},
                        "duration_min": {"type": "integer", "minimum": 0},
                        "intensity": {"type": "string", "enum": sorted(_INTENSITIES)},
                        "detail": {"type": "string"},
                    },
                    "required": ["date", "type", "duration_min", "intensity"],
                },
            }
        },
        "required": ["sessions"],
    },
    handler=_build_week,
    is_proposal=True,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -k "build_week or emit_week_tool" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/meso/generator.py tests/runtime_v0/test_meso_generator.py
git commit -m "feat(meso): emit_week tool + typed-week parser

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `generate_week` loop (happy, retry, prose-repair)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/meso/generator.py`
- Test: `tests/runtime_v0/test_meso_generator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/runtime_v0/test_meso_generator.py` (add imports):

```python
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.meso.generator import generate_week
```

```python
def _emit(sessions):
    return LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": sessions}),))


# A healthy build week for band (300, 330): key threshold Tue + easy + easy + long.
# load = 100 + 60 + 50 + 105 = 315 (in band); Tue/Sun stress not adjacent.
_GOOD_WEEK = [
    {"date": "2026-06-09", "type": "threshold", "duration_min": 50, "intensity": "hard"},   # 100
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 60, "intensity": "easy"},     # 60
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 50, "intensity": "easy"},     # 50
    {"date": "2026-06-14", "type": "long_run", "duration_min": 70, "intensity": "moderate"}, # 105
]
_LOW_WEEK = [{"date": "2026-06-09", "type": "easy_run", "duration_min": 30, "intensity": "easy"}]


def test_generate_week_passes_first_try():
    llm = FakeLLMClient([_emit(_GOOD_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.source == "llm"
    assert proposal.attempts == 1
    assert proposal.verdict.ok
    assert proposal.verdict.requires_pending is True


def test_generate_week_retries_then_passes():
    llm = FakeLLMClient([_emit(_LOW_WEEK), _emit(_GOOD_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.source == "llm"
    assert proposal.attempts == 2
    # the 2nd request carried the verifier violations from attempt 1
    second_messages = llm.requests[1]["messages"]
    assert any("load_drop" in m.get("content", "") for m in second_messages)


def test_generate_week_repairs_prose():
    llm = FakeLLMClient([LLMResponse(text="voici ta semaine ..."), _emit(_GOOD_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.attempts == 2
    second_messages = llm.requests[1]["messages"]
    assert any("emit_week" in m.get("content", "") for m in second_messages)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -k generate_week -v`
Expected: FAIL — `ImportError: cannot import name 'generate_week'`.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/src/fitmas/runtime_v0/meso/generator.py`:

```python
@dataclass(frozen=True)
class WeekProposal:
    week: PlannedWeek
    verdict: WeekVerdict
    source: Literal["llm", "template_fallback"]
    attempts: int


def generate_week(
    llm: LLMClient,
    pack: ContextPack,
    week_start: date,
    mode: Mode = "continuity",
    max_attempts: int = 3,
) -> WeekProposal:
    """Generate one typed week from the pack, looping generate->verify, then fallback.

    Requires pack.target (continuity); cold-start seed is out of scope (Slice 3).
    """
    if pack.target is None:
        raise ValueError("generate_week requires a target (continuity); cold-start is Slice 3")
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": render_generation_prompt(pack, week_start, mode)}
    ]
    for attempt in range(1, max_attempts + 1):
        response = llm.chat_with_tools(GENERATION_SYSTEM, messages, [EMIT_WEEK_TOOL])
        call = _emit_call(response)
        if call is None:
            messages.append(_contract_msg("emit the week via the emit_week tool, no prose"))
            continue
        try:
            week = _build_week(call.args.get("sessions", []))
        except (ValueError, KeyError, TypeError) as exc:
            messages.append(_contract_msg(f"invalid week: {exc}"))
            continue
        verdict = verify_week(week, pack.target, pack.constraints, mode)
        if verdict.ok:
            return WeekProposal(week=week, verdict=verdict, source="llm", attempts=attempt)
        messages.append(_violations_msg(verdict.violations))
    week = _template_week(pack.target, pack.constraints, week_start)
    verdict = verify_week(week, pack.target, pack.constraints, mode)
    return WeekProposal(week=week, verdict=verdict, source="template_fallback", attempts=max_attempts)


def _emit_call(response: LLMResponse) -> ToolCall | None:
    for call in response.tool_calls:
        if call.name == "emit_week":
            return call
    return None


def _contract_msg(error: str) -> dict[str, Any]:
    return {"role": "tool", "tool_name": "contract", "content": json.dumps({"error": error}, ensure_ascii=False)}


def _violations_msg(violations: tuple[Any, ...]) -> dict[str, Any]:
    payload = [{"code": v.code, "detail": v.detail, "severity": v.severity} for v in violations]
    return {"role": "tool", "tool_name": "verifier", "content": json.dumps(payload, ensure_ascii=False)}
```

(`_template_week` is added in Task 5; these loop tests never reach the fallback path, so they pass once `generate_week` exists. If your runner imports eagerly, add a temporary `def _template_week(*a, **k): raise NotImplementedError` — Task 5 replaces it. The Task-4 tests do not call it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -k generate_week -v`
Expected: PASS (3 tests). NameError on `_template_week` would only occur if a test reached the fallback — none here do. If import fails, add the temporary stub noted above.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/meso/generator.py tests/runtime_v0/test_meso_generator.py
git commit -m "feat(meso): generate_week loop (verify, retry on violations, prose repair)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Template fallback + cold-start guard

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/meso/generator.py`
- Test: `tests/runtime_v0/test_meso_generator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/runtime_v0/test_meso_generator.py`:

```python
def test_generate_week_falls_back_to_template():
    # LLM always emits an invalid (low, key-less) week -> 3 attempts -> template fallback.
    llm = FakeLLMClient([_emit(_LOW_WEEK), _emit(_LOW_WEEK), _emit(_LOW_WEEK)])
    proposal = generate_week(llm, _pack(), MONDAY)
    assert proposal.source == "template_fallback"
    assert proposal.attempts == 3
    assert proposal.verdict.ok  # the template is a verifiable standard week
    assert proposal.week.sessions  # non-empty


def test_template_respects_intensity_constraint():
    # Under an active intensity constraint the template emits no hard key (relaxed) and verifies.
    constraint = TypedConstraint(severity="moderate", restricts=("intensity",), active=True)
    llm = FakeLLMClient([_emit(_LOW_WEEK), _emit(_LOW_WEEK), _emit(_LOW_WEEK)])
    proposal = generate_week(llm, _pack((constraint,)), MONDAY)
    assert proposal.source == "template_fallback"
    assert proposal.verdict.ok
    assert all(not s.is_hard for s in proposal.week.sessions)


def test_generate_week_requires_target():
    bare = ContextPack(target=None, last_week_actuals=None, constraints=(), signals=())
    with pytest.raises(ValueError):
        generate_week(FakeLLMClient([]), bare, MONDAY)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -k "fallback or template or requires_target" -v`
Expected: FAIL — `NameError`/`NotImplementedError` on `_template_week` (and the fallback path is reached).

- [ ] **Step 3: Write minimal implementation**

In `backend/src/fitmas/runtime_v0/meso/generator.py`, add `_template_week` (replace the temporary stub if you added one):

```python
def _template_week(
    target: WeekTarget, constraints: tuple[TypedConstraint, ...], week_start: date
) -> PlannedWeek:
    """A deterministic standard running week sized to the band — the safety-net fallback.

    Targets the band midpoint across a fixed shape (key + long + 2 easy), spaced so the
    two high-stress days aren't adjacent. Under an active intensity/all constraint the
    key becomes an easy run (no hard work), matching the verifier's relaxation.
    """
    low, high = target.load_band
    mid = (low + high) / 2
    blocked = limits_intensity(constraints)

    def session(offset: int, kind: str, frac: float, intensity: str, weight: float) -> TypedSession:
        return TypedSession(
            date=week_start + timedelta(days=offset),
            type=kind,
            duration_min=max(10, round(mid * frac / weight)),
            intensity=intensity,
            detail="template fallback",
        )

    sessions = [
        session(1, "easy_run", 0.30, "easy", 1.0)
        if blocked
        else session(1, target.key_type, 0.30, "hard", 2.0),
        session(3, "easy_run", 0.20, "easy", 1.0),
        session(5, "easy_run", 0.15, "easy", 1.0),
        session(6, "long_run", 0.35, "moderate", 1.5),
    ]
    return PlannedWeek(sessions=tuple(sessions))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_meso_generator.py -v`
Expected: PASS (all generator tests).

Note: verify the template lands in-band for `(300, 330)`: key 100→`round(315*.3/2)=47`→94, easy `round(315*.2)=63`→63, easy `round(315*.15)=47`→47, long `round(315*.35/1.5)=74`→111. Total ≈ 315, inside (300, 330). If a future band makes it drift out, the test will catch it.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/meso/generator.py tests/runtime_v0/test_meso_generator.py
git commit -m "feat(meso): deterministic template fallback + cold-start guard

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Offline 4-6 week harness, docs, budget, full suite

**Files:**
- Create: `scripts/v0_eval/generate_weeks.py`
- Modify: `tests/runtime_v0/test_import_boundaries.py`, `docs/BUILD-ORDER.md`, `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md`

- [ ] **Step 1: Create the offline harness (no unit test — couche 2 manual)**

Create `scripts/v0_eval/generate_weeks.py`. It chains weeks via a real provider and prints them for hand-verification vs the app. Reuse the existing provider client from `scripts/v0_eval/provider_clients.py` (read it first to match its constructor/usage; it exposes the same `chat_with_tools` interface as `LLMClient`).

```python
"""Offline 4-6 week Meso generation harness (couche 2, manual).

Chains: seed actuals -> build target -> generate_week (real provider) -> verify ->
reduce to actuals -> repeat. Prints each week + verdict for hand-verification vs the
app (the TSS-drop case). Not a unit test; needs a provider API key. Exports not committed.

Usage: .venv/bin/python scripts/v0_eval/generate_weeks.py --provider deepseek --weeks 5
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from fitmas.runtime_v0.meso.generator import generate_week
from fitmas.runtime_v0.meso.model import ContextPack, WeekActuals, actuals_from_week, derive_continuity_target

from provider_clients import build_provider  # adapt to the real factory name in provider_clients.py


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--weeks", type=int, default=5)
    args = parser.parse_args()

    llm = build_provider(args.provider)
    actuals = WeekActuals(total_load=300.0, key_type="threshold")  # seed
    monday = date(2026, 6, 8)

    for index in range(1, args.weeks + 1):
        pack = ContextPack(
            target=derive_continuity_target(actuals),
            last_week_actuals=actuals,
            constraints=(),
            signals=(),
        )
        proposal = generate_week(llm, pack, monday)
        print(f"\n=== week {index} ({monday}) source={proposal.source} attempts={proposal.attempts} ok={proposal.verdict.ok}")
        for s in proposal.week.sessions:
            print(f"  {s.date} {s.type:12} {s.duration_min:3}min {s.intensity:8} load={s.load}")
        print(f"  week_load={proposal.week.week_load} band={proposal.verdict and pack.target.load_band}")
        if proposal.verdict.violations:
            print(f"  violations: {[v.code for v in proposal.verdict.violations]}")
        actuals = actuals_from_week(proposal.week)  # forward-only chaining
        monday = monday + timedelta(days=7)


if __name__ == "__main__":
    main()
```

Adapt `build_provider` / import to the real name in `scripts/v0_eval/provider_clients.py`. Do a wiring smoke check only (it needs a real key to fully run):

Run: `.venv/bin/python -c "import ast; ast.parse(open('scripts/v0_eval/generate_weeks.py').read()); print('parse ok')"`
Expected: `parse ok`.

- [ ] **Step 2: Run the full suite (no regression)**

Run: `.venv/bin/python -m pytest tests/runtime_v0 -q`
Expected: all PASS (209 from Slice 2.0 + the new generator/verifier tests). Record the count.

- [ ] **Step 3: Measure core LOC and bump the cap**

Run:
```bash
find backend/src/fitmas/runtime_v0 -name '*.py' -not -path '*__pycache__*' -not -path '*adapters*' -not -name '* 2.py' -print0 | xargs -0 wc -l | tail -1
```
Record the total `N`. In `tests/runtime_v0/test_import_boundaries.py`, set the cap to `N` rounded up to the next 10 + 10 headroom (e.g. N=3902 → cap 3920), and extend the comment:

```python
    # 3720 -> <CAP> (6 juin 2026): Slice 2.1 generator (generator.py, week_generation
    # prompt, constraint-aware relaxation). Core capability — the LLM-first week
    # generator + generate->verify loop. Bump per real growth only; ratchet target 2500.
    loc = sum(len(path.read_text().splitlines()) for path in _core_files())
    assert loc <= <CAP>
```

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_import_boundaries.py -v`
Expected: PASS.

- [ ] **Step 4: Update docs**

In `docs/BUILD-ORDER.md`: update the "Avancement" paragraph — Slice 2.1 codée (générateur LLM-first + boucle generate→verify + template filet + anti-drop contrainte-aware) ; pointer vers le design `2026-06-06-slice-2-1-generator-design.md` ; suite immédiate = **Slice 3** (tool runtime `propose_week` coach-callable). Update the "core : NNNN LOC (cap NNNN ...)" and "tests : NNN passed" numbers to the real measured values.

In `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md`: mark the slice table row **2.1 — Générateur** with ✅ and a short note (LLM-first, template filet, anti-drop contrainte-aware Tier 2, offline prouvé) ; update the "Fait le 5 juin ... Suite" line so 2.1 is in the fait list and Suite = **Slice 3**.

- [ ] **Step 5: Commit**

```bash
git add scripts/v0_eval/generate_weeks.py tests/runtime_v0/test_import_boundaries.py docs/BUILD-ORDER.md docs/superpowers/specs/2026-06-05-moteur-sport-plan.md
git commit -m "feat(meso): offline week-generation harness + budget bump + Slice 2.1 docs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Generator interface (`generate_week`, `WeekProposal`, `EMIT_WEEK_TOOL`) → Tasks 3, 4. ✅
- LLM-first generate→verify loop, structured-violation feedback, prose repair, max 3 → Task 4. ✅
- Template fallback (constraint-respecting) → Task 5. ✅
- Tier 2 anti-drop constraint-aware (relax load_drop + key on intensity/all) → Task 1. ✅
- Anti-gaming by construction (pack-driven, not declared) → Task 1 (`limits_intensity` reads pack constraints). ✅
- Cold-start requires target → Task 5 (`test_generate_week_requires_target`). ✅
- Generation prompt rendering the pack → Task 2. ✅
- Offline 4-6 week real-provider harness → Task 6. ✅
- Isolation (only runtime_v0-internal imports) → generator imports `llm_clients.base`, `meso.*`, `prompts.week_generation` (all internal). ✅
- LOC budget bump on real growth → Task 6. ✅
- Everything pending → `verify_week` returns `requires_pending=True`, asserted Task 1/4. ✅

**Placeholder scan:** no TBD/TODO. The one cross-task forward reference (`_template_week` used in Task 4, defined in Task 5) is called out explicitly with a temporary-stub instruction, and no Task-4 test reaches that path.

**Type consistency:** `generate_week(llm, pack, week_start, mode, max_attempts)`, `WeekProposal{week, verdict, source, attempts}`, `_build_week(sessions)->PlannedWeek`, `_template_week(target, constraints, week_start)`, `limits_intensity(constraints)->bool`, `verify_week(week, target, constraints, mode)` — names/signatures consistent across all tasks and aligned with the existing `verifier.py` and `llm_clients.base` (`LLMResponse`, `ToolCall`, `ToolSchema`, `FakeLLMClient(responses)`).
