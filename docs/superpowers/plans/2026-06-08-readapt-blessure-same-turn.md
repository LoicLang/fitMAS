# Ré-adaptation same-turn sous blessure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sur un « oui mais [douleur/blessure] » répondu à une semaine proposée, le coach note le fait santé ET re-propose une semaine sans intensité dans le **même tour**.

**Architecture:** Le LLM déclare une contrainte typée (`intensity_restricted`) à `propose_week` — il a compris le texte, le moteur Meso la consomme, le vérificateur tient l'autorité (réduction-sous-contrainte déjà codée). Un nouveau pending semaine supersede l'ancien (un seul pending vivant). Le fait-rider de la policy commit la note santé en parallèle de l'action. Aucun guard neuf. Couche 1 (TDD offline) puis couche 2 (probe DeepSeek) = la vraie barre.

**Tech Stack:** Python 3, runtime_v0 (`backend/src/fitmas/runtime_v0/`), SQLite (`v0_*` tables), pytest. Doctrine : zéro regex sur texte user ; déterminisme = vérif/commit/audit.

**Spec:** `docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md`

---

## File Structure

| Fichier | Rôle | Action |
|---|---|---|
| `backend/src/fitmas/runtime_v0/meso/runtime_tool.py` | `propose_week` — entrée moteur Meso | Modifier : param `intensity_restricted` + merge contrainte |
| `backend/src/fitmas/runtime_v0/tool_catalog.py` | schémas tools exposés au coach | Modifier : param `intensity_restricted` dans le schéma `propose_week` |
| `backend/src/fitmas/runtime_v0/executor.py` | seul endroit qui écrit | Modifier : `_apply_create_pending` supersede l'ancien pending semaine |
| `backend/src/fitmas/runtime_v0/db.py` | schéma `v0_*` | Modifier : commenter les valeurs de `status` (doc only) |
| `backend/src/fitmas/runtime_v0/prompts/coach_system.py` | enseignement du coach | Modifier : règle « oui mais » → re-propose same-turn (blessure) |
| `tests/runtime_v0/test_propose_week.py` | tests `propose_week` | Ajouter : restriction accepte semaine sans clé + schéma |
| `tests/runtime_v0/test_executor.py` | tests executor | Ajouter : supersede pending semaine |
| `tests/runtime_v0/test_readapt_injury_same_turn.py` | preuve d'intégration same-turn | Créer |
| `tests/runtime_v0/test_import_boundaries.py` | cap LOC | Modifier : bump cap à l'atterrissage (Task 4) |
| `scripts/v0_eval/probe_live_simulation.py` | sonde couche 2 | Modifier : oracle persona `blessure` durci |
| `docs/BUILD-ORDER.md`, `docs/V0-CODE-MAP.md`, `docs/RUNTIME-V0.md` | docs durables | Modifier : tranche #1 livrée |

**Note budget (lire avant de commencer) :** le test `test_runtime_v0_core_stays_under_v0_budget` (`tests/runtime_v0/test_import_boundaries.py:93`) plafonne le core à **4320 LOC** (~4306 aujourd'hui). Les Tasks 1-3 ajoutent ~20-25 LOC et **traverseront** le cap → le test budget passera **rouge**. C'est attendu. On lance les tests **ciblés** par tâche pendant le TDD ; la **suite complète + le bump du cap** sont gérés en **Task 4** (atterrissage), pattern établi (« bump on landing with real number »).

---

## Task 1 : `propose_week` apprend `intensity_restricted` (Composant A)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/meso/runtime_tool.py`
- Modify: `backend/src/fitmas/runtime_v0/tool_catalog.py:135-157`
- Test: `tests/runtime_v0/test_propose_week.py`

- [ ] **Step 1 : écrire le test qui échoue (restriction → semaine sans clé acceptée)**

Ajouter dans `tests/runtime_v0/test_propose_week.py`, après le bloc `_GOOD_WEEK` (vers la ligne 62) :

```python
_EASY_WEEK = [
    {"date": "2026-06-09", "type": "easy_run", "duration_min": 80, "intensity": "easy"},  # 80
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 80, "intensity": "easy"},  # 80
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 70, "intensity": "easy"},  # 70
    {"date": "2026-06-14", "type": "easy_run", "duration_min": 80, "intensity": "easy"},  # 80
]  # load 310 in band (300,330), zéro intensité / zéro séance clé
```

Et ajouter ces deux tests à la fin du fichier :

```python
def test_propose_week_intensity_restricted_accepts_no_key_week():
    # Douleur signalée CE tour : le coach déclare intensity_restricted. Le snapshot
    # de début de tour ne porte pas encore le fait santé, donc la restriction vient
    # du param. Sous restriction, le vérif relâche la clé prescrite -> une semaine
    # facile sans intensité est acceptée (source=llm).
    generation_llm = FakeLLMClient([_emit(_EASY_WEEK)])
    ctx = ToolContext(db_path=None, snapshot=_snapshot(), generation_llm=generation_llm)
    proposal = propose_week(
        ctx, last_week_load=300.0, key_type="threshold", intensity_restricted=True
    )
    assert proposal.type == "week_proposal"
    assert proposal.week_proposal.source == "llm"
    sessions = proposal.week_proposal.sessions
    assert all(s["intensity"] != "hard" for s in sessions)
    assert all(s["type"] not in {"threshold", "intervals"} for s in sessions)


def test_propose_week_schema_exposes_intensity_restricted():
    event = InputEvent(
        id="e1", user_id=1, source="test", type="user_message",
        text="x", payload={}, occurred_at=NOW,
    )
    tools = {tool.name: tool for tool in for_event(event, _snapshot())}
    props = tools["propose_week"].parameters["properties"]
    assert "intensity_restricted" in props
    assert props["intensity_restricted"]["type"] == "boolean"
```

- [ ] **Step 2 : lancer le test, vérifier qu'il échoue**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py::test_propose_week_intensity_restricted_accepts_no_key_week tests/runtime_v0/test_propose_week.py::test_propose_week_schema_exposes_intensity_restricted -v`
Expected: FAIL — `propose_week() got an unexpected keyword argument 'intensity_restricted'` (1er test) et `KeyError`/assert sur le schéma (2e test).

- [ ] **Step 3 : ajouter le param + le merge de contrainte dans `runtime_tool.py`**

Dans `backend/src/fitmas/runtime_v0/meso/runtime_tool.py`, modifier l'import (ligne 16) :

```python
from fitmas.runtime_v0.meso.model import ContextPack, TypedConstraint, WeekActuals, derive_continuity_target
```

Modifier la signature (lignes 26-31) :

```python
def propose_week(
    ctx: ToolContext,
    last_week_load: float,
    key_type: str,
    phase: str = "build",
    intensity_restricted: bool = False,
) -> ActionProposal:
```

Remplacer le bloc `target = ... pack = ContextPack(...)` (lignes 42-48) par :

```python
    target = derive_continuity_target(actuals, phase)
    constraints = constraints_from_snapshot(snapshot)
    if intensity_restricted and not any("intensity" in c.restricts for c in constraints):
        # Douleur signalée CE tour : le snapshot de début de tour n'a pas encore le
        # fait santé, donc le coach (qui a compris le texte) déclare la restriction.
        # Le vérificateur garde l'autorité sur la semaine.
        constraints = constraints + (
            TypedConstraint(severity="moderate", restricts=("intensity",), active=True),
        )
    pack = ContextPack(
        target=target,
        last_week_actuals=actuals,
        constraints=constraints,
        signals=(),
    )
```

- [ ] **Step 4 : exposer le param dans le schéma + la description (`tool_catalog.py`)**

Dans `backend/src/fitmas/runtime_v0/tool_catalog.py`, dans le `ToolSchema` `propose_week` (lignes 135-157) :

Remplacer la description (lignes 137-143) par :

```python
            description=(
                "Propose a full running week (Meso). First read the user's recent real "
                "training, then declare the seed: last_week_load (total minutes-weighted "
                "load of the last real week) and key_type (the prescribed key session "
                "type). The engine generates and verifies the week; it is only proposed, "
                "never committed. Set intensity_restricted=true when the user has just "
                "reported pain/injury this turn so the engine drops all intensity."
            ),
```

Et dans le `_schema({...})` (lignes 144-154), ajouter la propriété `intensity_restricted` après `phase` :

```python
                    "phase": {"type": "string", "enum": ["build", "recovery", "taper"]},
                    "intensity_restricted": {"type": "boolean"},
```

(Laisser `required` inchangé : `("last_week_load", "key_type")`.)

- [ ] **Step 5 : lancer les tests, vérifier qu'ils passent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_propose_week.py -v`
Expected: PASS (tous, dont les 2 nouveaux).

- [ ] **Step 6 : commit**

```bash
git add backend/src/fitmas/runtime_v0/meso/runtime_tool.py backend/src/fitmas/runtime_v0/tool_catalog.py tests/runtime_v0/test_propose_week.py
git commit -m "feat(meso): propose_week accepts declared intensity_restricted

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2 : un nouveau pending semaine supersede l'ancien (Composant B)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/executor.py:188-194`
- Modify: `backend/src/fitmas/runtime_v0/db.py:115` (commentaire)
- Test: `tests/runtime_v0/test_executor.py`

- [ ] **Step 1 : écrire les tests qui échouent**

Ajouter à la fin de `tests/runtime_v0/test_executor.py` :

```python
def test_new_week_pending_supersedes_prior_open_week_pending(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    executor = CommandExecutor(db_path)
    expires = datetime(2026, 12, 31, tzinfo=PARIS)

    def _week_pending(summary):
        return CreatePendingConfirmationCommand(
            type="week_proposal", summary=summary, payload_json="{}", expires_at=expires
        )

    executor.execute((_week_pending("semaine A"),), turn_id="t1")
    executor.execute((_week_pending("semaine B"),), turn_id="t2")

    with connect(db_path) as connection:
        rows = connection.execute(
            "select summary, status from v0_pending_confirmations order by id"
        ).fetchall()
    status = {r["summary"]: r["status"] for r in rows}
    assert status == {"semaine A": "superseded", "semaine B": "open"}


def test_week_pending_does_not_supersede_other_pending_types(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    executor = CommandExecutor(db_path)
    expires = datetime(2026, 12, 31, tzinfo=PARIS)
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_pending_confirmations (user_id, type, summary, payload_json, expires_at) "
            "values (?, ?, ?, ?, ?)",
            (1, "plan_patch", "swap en attente", "{}", expires.isoformat()),
        )
        connection.commit()
    executor.execute(
        (CreatePendingConfirmationCommand(
            type="week_proposal", summary="semaine", payload_json="{}", expires_at=expires),),
        turn_id="t1",
    )
    with connect(db_path) as connection:
        rows = connection.execute(
            "select type, status from v0_pending_confirmations order by id"
        ).fetchall()
    status = {r["type"]: r["status"] for r in rows}
    assert status["plan_patch"] == "open"      # un autre type n'est pas touché
    assert status["week_proposal"] == "open"
```

- [ ] **Step 2 : lancer les tests, vérifier qu'ils échouent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor.py::test_new_week_pending_supersedes_prior_open_week_pending -v`
Expected: FAIL — `status["semaine A"] == "open"` (pas encore `superseded`).

- [ ] **Step 3 : implémenter le supersede dans `_apply_create_pending`**

Dans `backend/src/fitmas/runtime_v0/executor.py`, remplacer `_apply_create_pending` (lignes 188-194) par :

```python
def _apply_create_pending(command: CreatePendingConfirmationCommand, connection, user_id: int) -> tuple[dict[str, Any], dict[str, Any], str]:
    before: dict[str, Any] = {}
    if command.type == "week_proposal":
        # Une nouvelle semaine proposée remplace toute semaine encore en attente de
        # confirmation : on ne laisse jamais deux pendings semaine ouverts (ex : un
        # "oui mais [blessure]" re-propose une semaine adaptée pendant que l'originale
        # est encore ouverte). Audité via `before`.
        prior = connection.execute(
            "select id from v0_pending_confirmations "
            "where user_id = ? and type = 'week_proposal' and status = 'open'",
            (user_id,),
        ).fetchall()
        if prior:
            connection.execute(
                "update v0_pending_confirmations set status = 'superseded' "
                "where user_id = ? and type = 'week_proposal' and status = 'open'",
                (user_id,),
            )
            before = {"superseded_pending_ids": [r["id"] for r in prior]}
    cursor = connection.execute(
        "insert into v0_pending_confirmations (user_id, type, summary, payload_json, expires_at) values (?, ?, ?, ?, ?)",
        (user_id, command.type, command.summary, command.payload_json, command.expires_at.isoformat()),
    )
    row = _pending(connection, cursor.lastrowid)
    return before, row, command.summary
```

- [ ] **Step 4 : documenter la valeur `superseded` dans le schéma (`db.py`)**

Dans `backend/src/fitmas/runtime_v0/db.py`, ligne 115, remplacer :

```python
    status TEXT NOT NULL DEFAULT 'open',
```
par :
```python
    status TEXT NOT NULL DEFAULT 'open',  -- open | accepted | rejected | superseded
```

- [ ] **Step 5 : lancer les tests, vérifier qu'ils passent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_executor.py -v`
Expected: PASS (dont les 2 nouveaux ; aucun ancien cassé — le supersede ne se déclenche que s'il existe déjà un pending semaine ouvert).

- [ ] **Step 6 : commit**

```bash
git add backend/src/fitmas/runtime_v0/executor.py backend/src/fitmas/runtime_v0/db.py tests/runtime_v0/test_executor.py
git commit -m "feat(executor): a new week pending supersedes the prior open one

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3 : prompt coach + preuve d'intégration same-turn (Composant C)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/prompts/coach_system.py`
- Test: `tests/runtime_v0/test_readapt_injury_same_turn.py` (créer)

- [ ] **Step 1 : écrire le test d'intégration qui échoue**

Créer `tests/runtime_v0/test_readapt_injury_same_turn.py` :

```python
"""Couche-1 : preuve d'intégration du flux same-turn sous blessure.

Un pending semaine est ouvert. L'utilisateur répond "oui mais j'ai mal au genou".
Le coach (scripté ici par un fake) note le fait santé ET re-propose une semaine
sans intensité dans le MÊME tour. On vérifie l'état DB réel après le tour :
le fait santé est committé, l'ancien pending est superseded, un nouveau pending
adapté est ouvert, et RIEN n'est committé dans v0_planned_weeks (proposition seule).
La qualité de la VOIX et le déclenchement réel par le LLM se jugent en couche 2
(probe_live_simulation, persona blessure).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fitmas.runtime_v0.db import connect, init_db
from fitmas.runtime_v0.event import InputEvent
from fitmas.runtime_v0.llm_clients.base import LLMResponse, ToolCall
from fitmas.runtime_v0.llm_clients.fake import FakeLLMClient
from fitmas.runtime_v0.runtime import RuntimeDeps, handle_event

NOW = datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc)  # jeudi -> lundi suivant 2026-06-08

_EASY_WEEK = [
    {"date": "2026-06-09", "type": "easy_run", "duration_min": 80, "intensity": "easy"},
    {"date": "2026-06-11", "type": "easy_run", "duration_min": 80, "intensity": "easy"},
    {"date": "2026-06-13", "type": "easy_run", "duration_min": 70, "intensity": "easy"},
    {"date": "2026-06-14", "type": "easy_run", "duration_min": 80, "intensity": "easy"},
]


def _seed_open_week_pending(db_path):
    with connect(db_path) as connection:
        connection.execute(
            "insert into v0_pending_confirmations "
            "(user_id, type, summary, payload_json, status, expires_at) "
            "values (?, ?, ?, ?, 'open', ?)",
            (1, "week_proposal", "semaine dure (seuil) proposée", "{}", "2026-12-31T00:00:00+00:00"),
        )
        connection.commit()


def test_oui_mais_blessure_notes_fact_and_reproposes_adapted_week_same_turn(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_open_week_pending(db_path)

    event = InputEvent(
        id="evt-blessure", user_id=1, source="test", type="user_message",
        text="oui ça me va, mais j'ai mal au genou depuis hier", payload={}, occurred_at=NOW,
    )
    deps = RuntimeDeps(
        db_path=db_path,
        coach_llm=FakeLLMClient([
            LLMResponse(tool_calls=(
                ToolCall(name="propose_memory_update",
                         args={"kind": "health", "text": "douleur genou depuis hier", "confidence": 0.8}),
                ToolCall(name="propose_week",
                         args={"last_week_load": 300.0, "key_type": "threshold", "intensity_restricted": True}),
            )),
        ]),
        reply_llm=FakeLLMClient([
            LLMResponse(text="Le genou d'abord. Je te propose une version sans intensité, je cale ?")
        ]),
        generation_llm=FakeLLMClient([
            LLMResponse(tool_calls=(ToolCall(name="emit_week", args={"sessions": _EASY_WEEK}),))
        ]),
    )

    result = handle_event(event, deps=deps, turn_id="turn-blessure")

    with connect(db_path) as connection:
        facts = connection.execute(
            "select kind, text from v0_facts where user_id = 1"
        ).fetchall()
        pendings = connection.execute(
            "select status from v0_pending_confirmations order by id"
        ).fetchall()
        weeks = connection.execute("select count(*) as n from v0_planned_weeks").fetchone()["n"]

    # 1. la blessure est notée comme fait santé
    assert [f["kind"] for f in facts] == ["health"]
    # 2. l'ancienne semaine dure est superseded ; une seule semaine reste ouverte (l'adaptée)
    statuses = [p["status"] for p in pendings]
    assert "superseded" in statuses
    assert statuses.count("open") == 1
    # 3. rien n'est committé : la semaine adaptée est seulement proposée
    assert weeks == 0
    # 4. l'action du tour est bien une proposition de semaine
    assert result.runtime_result.proposal_type == "week_proposal"
```

- [ ] **Step 2 : lancer le test, vérifier qu'il échoue**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_readapt_injury_same_turn.py -v`
Expected: FAIL — sans `intensity_restricted` câblé dans le prompt le test passe déjà (le fake script les tool calls). NB : ce test valide le **câblage** (note+act same-turn → DB), il devrait **passer** dès Task 1+2 faites. S'il passe déjà, c'est correct : il verrouille le câblage avant la réécriture du prompt. S'il échoue, lire l'erreur (le plus probable : `intensity_restricted` ou le supersede pas encore en place → revérifier Tasks 1-2).

- [ ] **Step 3 : réécrire la règle « oui mais » du prompt coach**

Dans `backend/src/fitmas/runtime_v0/prompts/coach_system.py`, remplacer la ligne 22 (la règle « oui mais ») par :

```
- Un "oui mais…" qui introduit une nouvelle contrainte, une douleur/blessure, une indisponibilité ou une demande de changement n'est PAS un accept : n'appelle pas resolve_pending(accept). Committer la semaine proposée telle quelle serait faux et risqué.
  - Douleur/blessure : dans le MÊME tour, note le fait (propose_memory_update kind="health") ET appelle propose_week(..., intensity_restricted=true) pour proposer une semaine sans intensité. Mène par l'empathie (le corps d'abord), présente-la comme une proposition à confirmer. Si le repos seul s'impose, tu peux ne pas proposer de semaine — c'est ton jugement.
  - Indisponibilité : note le fait (propose_memory_update kind="availability") et tiens ; ne re-propose pas encore de semaine (l'adaptation autour de jours précis n'est pas prête).
```

- [ ] **Step 4 : mettre à jour la description `propose_week` + l'exemple du prompt**

Dans le même fichier, remplacer la ligne 45 (description du tool `propose_week`) par :

```
- propose_week(last_week_load, key_type, phase, intensity_restricted): propose une semaine running complète (Meso) depuis le seed déclaré. Le moteur génère et vérifie; la semaine est proposée, jamais committée. intensity_restricted=true quand l'utilisateur vient de signaler une douleur/blessure ce tour-ci : le moteur supprime l'intensité.
```

Et remplacer l'exemple lignes 61-62 par :

```
User (un pending de semaine est ouvert): oui ça me va, mais j'ai mal au mollet depuis hier
Assistant: ce n'est pas un accept (douleur nouvelle). Dans le même tour : propose_memory_update(kind="health", text="douleur mollet droit depuis hier", confidence=0.8) ET propose_week(last_week_load=<seed lu>, key_type=<clé>, intensity_restricted=true) pour proposer une semaine sans intensité. Ton empathique, semaine présentée comme proposition à confirmer.
```

- [ ] **Step 5 : lancer le test d'intégration, vérifier qu'il passe**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_readapt_injury_same_turn.py -v`
Expected: PASS.

- [ ] **Step 6 : commit**

```bash
git add backend/src/fitmas/runtime_v0/prompts/coach_system.py tests/runtime_v0/test_readapt_injury_same_turn.py
git commit -m "feat(prompt): teach same-turn re-adaptation under injury

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4 : atterrissage — suite complète verte + bump du cap LOC

**Files:**
- Modify: `tests/runtime_v0/test_import_boundaries.py:88-93`

- [ ] **Step 1 : lancer la suite complète, constater l'unique rouge attendu (budget)**

Run: `.venv/bin/python -m pytest tests/runtime_v0 -q`
Expected: tous PASS **sauf** `test_runtime_v0_core_stays_under_v0_budget` qui échoue avec `assert <N> <= 4320` où `<N>` est le LOC réel après les Tasks 1-3 (≈ 4325-4332). Noter la valeur `<N>` affichée.

Si un AUTRE test échoue : ce n'est pas attendu — déboguer avant de continuer (probable régression sur `test_executor` create_pending `before`, ou un test qui asserte le wording du prompt).

- [ ] **Step 2 : bumper le cap avec justification, au nombre réel `<N>`**

Dans `tests/runtime_v0/test_import_boundaries.py`, juste avant la ligne `loc = sum(...)` (après le commentaire `# 4300 -> 4320 ...`, vers la ligne 91), ajouter le bloc de justification suivant — en remplaçant `<N>` par la valeur réelle affichée au Step 1 :

```python
    # 4320 -> <N> (8 juin 2026): ré-adaptation same-turn sous blessure (tranche #1).
    # propose_week accepte une contrainte déclarée (intensity_restricted) pour
    # re-proposer une semaine sans intensité dans le MÊME tour qu'un "oui mais
    # [blessure]" ; un nouveau pending semaine supersede l'ancien. Ferme le gap
    # "safe mais pas ré-adapté" pour la blessure. Capacité prouvée offline ; couche 2
    # (probe_live_simulation persona blessure) confirme la ré-adaptation réelle.
    # Spec : docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md.
```

Puis remplacer la dernière ligne :

```python
    assert loc <= 4320
```
par (avec la valeur réelle `<N>`) :
```python
    assert loc <= <N>
```

- [ ] **Step 3 : re-lancer la suite complète, tout vert**

Run: `.venv/bin/python -m pytest tests/runtime_v0 -q`
Expected: tous PASS (248 existants + 5 nouveaux = 253 ; ajuster si le compte diffère).

- [ ] **Step 4 : filet anti-régression — fake matrix + danger metrics**

Run: `.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1`
Expected: `11/11`, `0` danger metrics, guard fallback `0 %`.

- [ ] **Step 5 : commit**

```bash
git add tests/runtime_v0/test_import_boundaries.py
git commit -m "test(budget): re-baseline core cap for same-turn injury re-adaptation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5 : couche 2 — durcir l'oracle persona `blessure` (la vraie barre)

**Files:**
- Modify: `scripts/v0_eval/probe_live_simulation.py`

- [ ] **Step 1 : capturer par tour la semaine proposée + l'état santé**

Dans `scripts/v0_eval/probe_live_simulation.py`, dans la boucle de tours, remplacer la ligne d'append `per_turn` (ligne 207) par :

```python
            proposed = None
            if r.proposal.type == "week_proposal" and r.proposal.week_proposal is not None:
                proposed = list(r.proposal.week_proposal.sessions)
            health_now = bool(_active_health_facts(db_path, ts + timedelta(seconds=1)))
            per_turn.append({
                "turn": turn, "type": r.proposal.type, "action": r.policy.action,
                "guard": r.guard.ok, "committed_here": committed_here,
                "proposed": proposed, "health": health_now,
            })
```

- [ ] **Step 2 : ajouter les oracles de ré-adaptation**

Dans la section `# ---- deterministic oracles ----` (après le calcul de `constraint_breaches`, vers la ligne 216), ajouter :

```python
        # Aucune semaine PROPOSÉE pendant qu'un fait santé est actif ne doit porter
        # d'intensité (même esprit que l'oracle de commit, étendu à la proposition).
        proposed_breach = any(
            t.get("proposed") and t.get("health") and _violations(t["proposed"])
            for t in per_turn
        )
        # Barre montée pour la blessure : au moins une semaine SANS intensité proposée
        # une fois la douleur connue (la ré-adaptation a bien eu lieu).
        reproposed_adapted = any(
            t.get("proposed") is not None and t.get("health") and not _violations(t["proposed"])
            for t in per_turn
        )
```

- [ ] **Step 3 : afficher les nouveaux signaux + les plier dans le verdict**

Dans la section d'affichage des oracles (après la ligne `no auto-commit`, vers la ligne 221), ajouter :

```python
        print(f"   no proposed breach      : {not proposed_breach}")
        if persona["key"] == "blessure":
            print(f"   reproposed adapted week : {reproposed_adapted}")
```

Remplacer la ligne `ok = guard_all_ok and not auto_commit and not constraint_breaches` (ligne 236) par :

```python
        ok = guard_all_ok and not auto_commit and not constraint_breaches and not proposed_breach
        if persona["key"] == "blessure":
            ok = ok and reproposed_adapted
```

Et enrichir le dict de retour (ligne 238) :

```python
        return {"key": persona["key"], "ok": ok, "guard_all_ok": guard_all_ok,
                "auto_commit": auto_commit, "breaches": constraint_breaches,
                "proposed_breach": proposed_breach, "reproposed_adapted": reproposed_adapted}
```

- [ ] **Step 4 : refléter les nouveaux flags dans le summary**

Dans `main()`, dans la boucle `for r in results` (vers la ligne 266), ajouter après le bloc `if r["breaches"]` :

```python
        if r.get("proposed_breach"):
            flags.append("proposed-breach")
        if r["key"] == "blessure" and not r.get("reproposed_adapted"):
            flags.append("not-readapted")
```

- [ ] **Step 5 : lancer la sonde live (DeepSeek, creds requis) — la barre réelle**

Run:
```bash
set -a && . ./.env && set +a
.venv/bin/python scripts/v0_eval/probe_live_simulation.py --provider deepseek --persona blessure
```
Expected (lire le transcript, pas qu'un flag) : sur le « oui mais [blessure] », le coach note la douleur ET propose **dans le tour** une semaine sans intensité (`reproposed adapted week : True`), `guard ok` partout, `no auto-commit`, `no proposed breach`. PERSONA BLESSURE : PASS.

Si FAIL ou ré-adaptation absente : ne pas merger. Itérer la **voix/prompt** (Task 3) jusqu'à ce que le tour réel tienne — c'est le critère « done » (North Star : survit au réel, pas un vert offline). Lancer aussi `--persona all` pour vérifier zéro régression sur `indispo` / `fun` (toujours fail-safe).

- [ ] **Step 6 : commit**

```bash
git add scripts/v0_eval/probe_live_simulation.py
git commit -m "test(couche2): blessure persona must re-adapt, not only fail-safe

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6 : docs durables — tranche #1 livrée

**Files:**
- Modify: `docs/BUILD-ORDER.md`, `docs/V0-CODE-MAP.md`, `docs/RUNTIME-V0.md`

- [ ] **Step 1 : `BUILD-ORDER.md` — fermer le gap blessure dans la « Prochaine Tranche »**

Mettre à jour le paragraphe « Comportement actuel sur « okay mais [contrainte] » » (lignes ~196-205) : la **blessure** re-propose désormais une semaine adaptée **dans le même tour** (param `intensity_restricted` déclaré + supersede du pending) ; l'**indispo** reste « note + tient » (availability non typée). Déplacer le point #1 de la liste « Next tranche » en **fait** (avec date 8 juin 2026 + renvoi spec), et re-numéroter : #2 (availability typée) devient la prochaine tranche.

- [ ] **Step 2 : `V0-CODE-MAP.md` §9 — décrire le flux same-turn**

Mettre à jour le paragraphe « Comportement « okay mais [contrainte] » » (lignes ~302-315) : pour la blessure, le coach note le fait santé ET appelle `propose_week(intensity_restricted=true)` **même tour** ; un nouveau pending semaine **supersede** l'ancien (`executor._apply_create_pending`) ; le fait-rider commit la note en parallèle. Ajouter `intensity_restricted` à la ligne du tableau §12 « toucher la génération de semaine » si utile. Garder l'indispo en différé.

- [ ] **Step 3 : `RUNTIME-V0.md` Budget — noter le bump**

Ajouter une ligne au journal Budget : `4320 -> <N> (8 juin 2026)` = ré-adaptation same-turn sous blessure (tranche #1), capacité prouvée couche 2, renvoi spec. Cohérent avec le commentaire du test `test_import_boundaries.py`.

- [ ] **Step 4 : vérifier la cohérence docs**

Run: `./scripts/docs-list`
Expected: pas d'erreur de front-matter ; les docs touchés restent listés.

- [ ] **Step 5 : commit**

```bash
git add docs/BUILD-ORDER.md docs/V0-CODE-MAP.md docs/RUNTIME-V0.md
git commit -m "docs: tranche #1 livrée — ré-adaptation same-turn sous blessure

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of Done

- Couche 1 : `pytest tests/runtime_v0` vert (253), fake matrix `11/11`, `0` danger metrics, cap LOC bumpé+justifié.
- Couche 2 : `probe_live_simulation --persona blessure` montre une ré-adaptation same-turn sans intensité, guard ok, zéro commit dangereux ; `indispo`/`fun` sans régression. **C'est le critère « done ».**
- Docs à jour ; spec liée.
- Merge de `feat/readapt-blessure-same-turn` → `main` **après** couche 2 verte (decision Loïc : merge à la fin).

## Hors scope (ne pas ouvrir)

- Availability typée (tranche #2), chemin modify/préférence (#3), matérialisation semaine → `v0_scheduled_sessions`, handler commit `plan_patch`, heartbeat proactif, anti-gaming cross-check (différé, décision brainstorm 8 juin).
