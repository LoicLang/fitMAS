# Mini-Transcript Conversationnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner au coach V0 une mémoire court terme conversationnelle (4 derniers échanges verbatim dans le SnapshotHeader) + instrumenter la « promesse fantôme » (warning guard non bloquant `warn:confirmation_without_pending`).

**Architecture:** Le transcript est reconstruit **read-only** au build du snapshot (jointure `v0_input_events` × `v0_turns`), rendu dans `to_prompt_text()` — l'agent coach le voit sans câblage neuf (le reply LLM, lui, ne reçoit pas le header — corrigé post-landing, voir spec). Le guard gagne un canal `warnings` séparé des `blocked_reasons` (jamais bloquant, persisté avec préfixe `warn:` dans `guard_reasons_json`). Spec : `docs/superpowers/specs/2026-06-12-mini-transcript-design.md`.

**Tech Stack:** Python 3, sqlite3, pytest. Zéro nouvelle dépendance, zéro nouvelle table.

**Important — cap LOC :** `tests/runtime_v0/test_import_boundaries.py` casse à `loc <= 4586`. Les tâches 1-4 ajoutent du LOC core → lancer les tests **ciblés par fichier** pendant le dev ; le bump du cap (avec le chiffre réel) se fait en tâche 7 au landing. C'est la discipline existante (« bump ON LANDING with its real number »).

---

### Task 1: Transcript loader + champ snapshot

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/snapshot.py`
- Test: `tests/runtime_v0/test_snapshot.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter en bas de `tests/runtime_v0/test_snapshot.py` (les helpers `PARIS`, `init_db`, `connect`, `SnapshotBuilder` sont déjà importés en tête de fichier ; `timedelta` aussi) :

```python
def _insert_input_event(connection, event_id: str, now, text: str, hours_ago: float):
    connection.execute(
        "insert into v0_input_events (id, user_id, source, type, text, payload_json, occurred_at)"
        " values (?, 1, 'test', 'user_message', ?, '{}', ?)",
        (event_id, text, (now - timedelta(hours=hours_ago)).isoformat()),
    )


def _insert_turn_reply(connection, turn_id: str, event_id: str, reply: str):
    connection.execute(
        "insert into v0_turns (id, event_id, reply) values (?, ?, ?)",
        (turn_id, event_id, reply),
    )


def test_transcript_keeps_last_four_exchanges_chronological(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        for index in range(6):
            _insert_input_event(connection, f"evt-{index}", now, f"message {index}", hours_ago=6 - index)
            _insert_turn_reply(connection, f"turn-{index}", f"evt-{index}", f"reponse {index}")
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    entries = [(entry.role, entry.text) for entry in snapshot.recent_transcript]
    assert entries == [
        ("user", "message 2"), ("coach", "reponse 2"),
        ("user", "message 3"), ("coach", "reponse 3"),
        ("user", "message 4"), ("coach", "reponse 4"),
        ("user", "message 5"), ("coach", "reponse 5"),
    ]


def test_transcript_drops_messages_older_than_48h(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-old", now, "vieux message", hours_ago=49)
        _insert_turn_reply(connection, "turn-old", "evt-old", "vieille reponse")
        _insert_input_event(connection, "evt-new", now, "message frais", hours_ago=1)
        _insert_turn_reply(connection, "turn-new", "evt-new", "reponse fraiche")
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    assert [entry.text for entry in snapshot.recent_transcript] == ["message frais", "reponse fraiche"]


def test_transcript_excludes_current_event_and_foreign_user(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-prev", now, "tour precedent", hours_ago=2)
        _insert_turn_reply(connection, "turn-prev", "evt-prev", "reponse precedente")
        _insert_input_event(connection, "evt-current", now, "tour courant", hours_ago=0)
        connection.execute(
            "insert into v0_input_events (id, user_id, source, type, text, payload_json, occurred_at)"
            " values ('evt-autre', 2, 'test', 'user_message', 'autre user', '{}', ?)",
            ((now - timedelta(hours=1)).isoformat(),),
        )
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now, current_event_id="evt-current")

    assert [entry.text for entry in snapshot.recent_transcript] == ["tour precedent", "reponse precedente"]


def test_transcript_user_message_without_reply_stands_alone(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-crash", now, "message sans reponse", hours_ago=3)
        _insert_input_event(connection, "evt-nosend", now, "message no_send", hours_ago=2)
        _insert_turn_reply(connection, "turn-nosend", "evt-nosend", "")
        connection.commit()

    snapshot = SnapshotBuilder(db_path).build(user_id=1, now=now)

    assert [(entry.role, entry.text) for entry in snapshot.recent_transcript] == [
        ("user", "message sans reponse"),
        ("user", "message no_send"),
    ]
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_snapshot.py -v -k transcript`
Expected: 4 FAIL — `AttributeError: 'WorldSnapshot' object has no attribute 'recent_transcript'` (ou TypeError sur `current_event_id`).

- [ ] **Step 3: Implémenter dans snapshot.py**

Dans `backend/src/fitmas/runtime_v0/snapshot.py` :

(a) Après le dataclass `CommandEventView` (~ligne 57), ajouter :

```python
@dataclass(frozen=True)
class TranscriptEntry:
    role: Literal["user", "coach"]
    text: str
    at: datetime
```

(b) Sur `WorldSnapshot`, après `last_planned_week: WeekActuals | None = None` :

```python
    recent_transcript: tuple[TranscriptEntry, ...] = ()
```

(c) Signature de `SnapshotBuilder.build` :

```python
    def build(self, user_id: int, now: datetime, current_event_id: str | None = None) -> WorldSnapshot:
```

Dans le bloc `with connect(...)`, après `last_planned_week = ...` :

```python
            recent_transcript = _load_transcript(connection, user_id, now, current_event_id)
```

Et dans le constructeur `WorldSnapshot(...)` retourné : `recent_transcript=recent_transcript,`.

(d) Nouvelle fonction module-level, à côté de `_load_conversation_state` :

```python
def _load_transcript(connection, user_id: int, now: datetime, exclude_event_id: str | None) -> tuple[TranscriptEntry, ...]:
    cutoff = (now - timedelta(hours=48)).isoformat()
    rows = connection.execute(
        """
        select e.text, e.occurred_at, t.reply
        from v0_input_events e
        left join v0_turns t on t.event_id = e.id
        where e.user_id = ? and e.type = 'user_message'
          and e.text is not null and e.text != ''
          and e.occurred_at >= ?
          and e.id != ?
        order by e.occurred_at desc, e.id desc
        limit 4
        """,
        (user_id, cutoff, exclude_event_id or ""),
    ).fetchall()
    entries: list[TranscriptEntry] = []
    for row in reversed(rows):
        at = _parse_datetime(row["occurred_at"])
        entries.append(TranscriptEntry("user", row["text"], at))
        if row["reply"]:
            entries.append(TranscriptEntry("coach", row["reply"], at))
    return tuple(entries)
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_snapshot.py -v`
Expected: tous PASS (les anciens tests snapshot inclus — la signature a un défaut `None`).

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/snapshot.py tests/runtime_v0/test_snapshot.py
git commit -m "feat(runtime_v0): transcript 4 derniers echanges dans WorldSnapshot (read-only, 48h)"
```

---

### Task 2: Rendu header `recent_conversation` + budget 900

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/snapshot.py` (SnapshotHeader, to_prompt_text, header())
- Test: `tests/runtime_v0/test_snapshot.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/runtime_v0/test_snapshot.py` :

```python
def test_header_renders_recent_conversation_clipped(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    with connect(db_path) as connection:
        _insert_input_event(connection, "evt-a", now, "x" * 400, hours_ago=2)
        _insert_turn_reply(connection, "turn-a", "evt-a", "reponse courte")
        connection.commit()

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation:" in text
    assert "user: " + "x" * 299 + "…" in text
    assert "coach: reponse courte" in text
    assert "[12/06 10:00]" in text


def test_header_omits_recent_conversation_when_empty(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation" not in text


def test_header_word_budget_holds_with_full_transcript(tmp_path):
    db_path = tmp_path / "fitmas_v0.db"
    now = datetime(2026, 6, 12, 12, 0, tzinfo=PARIS)
    init_db(db_path)
    long_message = " ".join(["mot"] * 80)
    with connect(db_path) as connection:
        for offset in (0, 1, 2, 14):
            _insert_session(connection, now, offset)
        for index in range(4):
            _insert_input_event(connection, f"evt-{index}", now, long_message, hours_ago=4 - index)
            _insert_turn_reply(connection, f"turn-{index}", f"evt-{index}", long_message)
        connection.commit()

    text = SnapshotBuilder(db_path).build(user_id=1, now=now).header().to_prompt_text()

    assert "recent_conversation:" in text  # l'assert interne <= 900 mots n'a pas sauté
```

Note : `_insert_input_event` avec `hours_ago=2` sur un `now` à 12:00 → timestamp 10:00, d'où `[12/06 10:00]`.

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_snapshot.py -v -k header`
Expected: FAIL (`recent_conversation` absent du rendu ; le 3e test peut casser sur l'assert 500 mots).

- [ ] **Step 3: Implémenter le rendu**

Dans `backend/src/fitmas/runtime_v0/snapshot.py` :

(a) Sur `SnapshotHeader`, après `recent_training: tuple[SessionView, ...] = ()` :

```python
    recent_transcript: tuple[TranscriptEntry, ...] = ()
```

(b) Dans `WorldSnapshot.header()`, ajouter au constructeur retourné :

```python
            recent_transcript=self.recent_transcript,
```

(c) Dans `to_prompt_text()`, juste avant `text = "\n".join(lines)` :

```python
        if self.recent_transcript:
            lines.append("recent_conversation:")
            for entry in self.recent_transcript:
                stamp = entry.at.strftime("%d/%m %H:%M")
                lines.append(f"- [{stamp}] {entry.role}: {_clip(entry.text)}")
```

(d) Remplacer `assert len(text.split()) <= 500` par :

```python
        assert len(text.split()) <= 900
```

(e) Fonction module-level :

```python
def _clip(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
```

- [ ] **Step 4: Vérifier que les tests passent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_snapshot.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/fitmas/runtime_v0/snapshot.py tests/runtime_v0/test_snapshot.py
git commit -m "feat(runtime_v0): rendu recent_conversation dans le header (clip 300, budget 900 mots)"
```

---

### Task 3: Câblage runtime + enseignement prompt coach

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/runtime.py:71`
- Modify: `backend/src/fitmas/runtime_v0/prompts/coach_system.py` (~ligne 31)
- Test: `tests/runtime_v0/test_runtime_flow.py`

- [ ] **Step 1: Écrire le test d'intégration qui échoue**

Ajouter à `tests/runtime_v0/test_runtime_flow.py` (imports déjà présents : `handle_event`, `RuntimeDeps`, `FakeLLMClient`, `connect`, `init_db`, `datetime`, `timedelta`, `PARIS`) :

```python
def test_next_turn_snapshot_sees_previous_exchange(tmp_path):
    from fitmas.runtime_v0.snapshot import SnapshotBuilder

    db_path = tmp_path / "fitmas_v0.db"
    init_db(db_path)
    _seed_session(db_path)
    first = InputEvent(
        id="evt-fil-1", user_id=1, source="test", type="user_message",
        text="Tu peux deplacer ma seance a demain ?", payload={},
        occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=PARIS),
    )
    deps = RuntimeDeps(db_path=db_path, coach_llm=FakeLLMClient([]), reply_llm=FakeLLMClient([]))
    handle_event(first, deps=deps, turn_id="turn-fil-1")

    snapshot = SnapshotBuilder(db_path).build(
        user_id=1,
        now=datetime(2026, 5, 22, 14, 5, tzinfo=PARIS),
        current_event_id="evt-fil-2",
    )

    assert any(
        entry.role == "user" and entry.text == "Tu peux deplacer ma seance a demain ?"
        for entry in snapshot.recent_transcript
    )
```

- [ ] **Step 2: Vérifier l'état du test**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_runtime_flow.py::test_next_turn_snapshot_sees_previous_exchange -v`
Expected: PASS dès maintenant (persist_turn écrit l'input event en fin de tour). Ce test verrouille le contrat bout-en-bout ; s'il FAIL, lire l'erreur avant d'avancer.

- [ ] **Step 3: Câbler `current_event_id` dans runtime.py**

Ligne 71 de `backend/src/fitmas/runtime_v0/runtime.py`, remplacer :

```python
    snapshot = SnapshotBuilder(deps.db_path).build(event.user_id, event.occurred_at)
```

par :

```python
    snapshot = SnapshotBuilder(deps.db_path).build(event.user_id, event.occurred_at, current_event_id=event.id)
```

(Défensif : aujourd'hui l'input event n'est persisté qu'en fin de tour, mais un retry après échec partiel peut l'avoir déjà écrit.)

- [ ] **Step 4: Enseigner le fil au coach**

Dans `backend/src/fitmas/runtime_v0/prompts/coach_system.py`, localiser la ligne (~31) :

```text
pending et last_unresolved_intent. Pour plus de détail, appelle les tools.
```

Ajouter juste après, dans le même bloc de contexte :

```text
recent_conversation = le fil récent de vos échanges. Une réponse courte (« oui », « c'est bien ça », une préférence) se rattache à ta dernière proposition visible dans ce fil. Si tu avais proposé une action sans créer d'artefact (aucun pending ouvert), concrétise-la MAINTENANT (propose_plan_patch / propose_week) au lieu de redemander ou de répondre que tu n'as pas d'information.
```

- [ ] **Step 5: Lancer les tests ciblés**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_runtime_flow.py tests/runtime_v0/test_snapshot.py tests/runtime_v0/test_agent_tool_loop.py -v`
Expected: tous PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/runtime.py backend/src/fitmas/runtime_v0/prompts/coach_system.py tests/runtime_v0/test_runtime_flow.py
git commit -m "feat(runtime_v0): le coach voit le fil recent (cablage event_id + enseignement prompt)"
```

---

### Task 4: Guard — warning `confirmation_without_pending` (non bloquant)

**Files:**
- Modify: `backend/src/fitmas/runtime_v0/guard.py`
- Modify: `backend/src/fitmas/runtime_v0/runtime.py:94` (call site) et `_existing_result` (~ligne 171)
- Modify: `backend/src/fitmas/runtime_v0/audit.py:77`
- Test: `tests/runtime_v0/test_guard.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `tests/runtime_v0/test_guard.py` (helpers `_result`, `PendingView`, `OutputGuard`, `date`, `datetime`, `PARIS` déjà présents) :

```python
def test_confirmation_request_without_pending_warns_not_blocks():
    guard = OutputGuard(date(2026, 5, 22), pending_open=False)

    result = guard.verify("Un fractionné en fin de journée, tu me confirmes ?", _result())

    assert result.ok
    assert result.blocked_reasons == ()
    assert result.warnings == ("warn:confirmation_without_pending",)


def test_confirmation_request_with_open_pending_does_not_warn():
    guard = OutputGuard(date(2026, 5, 22), pending_open=True)

    result = guard.verify("Un fractionné en fin de journée, tu me confirmes ?", _result())

    assert result.ok
    assert result.warnings == ()


def test_confirmation_request_with_pending_created_this_turn_does_not_warn():
    pending = PendingView(7, "week_proposal", "semaine du 15 juin", datetime(2026, 5, 23, 14, 0, tzinfo=PARIS))
    guard = OutputGuard(date(2026, 5, 22), pending_open=False)

    result = guard.verify(
        "Je te propose la semaine du 15 juin, tu valides ?",
        _result(policy_action="requires_confirmation", pending=pending),
    )

    assert result.ok
    assert result.warnings == ()


def test_reply_without_confirmation_request_does_not_warn():
    guard = OutputGuard(date(2026, 5, 22), pending_open=False)

    result = guard.verify("Demain c'est footing facile, 35 minutes tranquilles.", _result())

    assert result.ok
    assert result.warnings == ()
```

- [ ] **Step 2: Vérifier qu'ils échouent**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_guard.py -v -k confirmation`
Expected: FAIL — `TypeError: OutputGuard.__init__() got an unexpected keyword argument 'pending_open'`.

- [ ] **Step 3: Implémenter dans guard.py**

(a) Après `TRUNCATED_END_PATTERN` :

```python
CONFIRMATION_REQUEST_PATTERN = re.compile(
    r"\b(tu me confirmes|tu confirmes|tu valides|ça te va|ça te convient|dis-moi si)\b",
    re.IGNORECASE,
)
```

Garde-fou doctrine (`BUILD-ORDER.md` failles ouvertes) : ne pas laisser grossir cette liste — si friction répétée, repenser, pas empiler.

(b) `GuardResult` gagne un champ par défaut (les constructions existantes `GuardResult(True, (), "")` restent valides) :

```python
@dataclass(frozen=True)
class GuardResult:
    ok: bool
    blocked_reasons: tuple[str, ...]
    sanitized_reply: str
    warnings: tuple[str, ...] = ()
```

(c) `OutputGuard.__init__` :

```python
    def __init__(self, today: date, pending_open: bool = False):
        self.today = today
        self.pending_open = pending_open
```

(d) Dans `verify`, juste avant `if reasons:` :

```python
        warnings: list[str] = []
        if (
            not self.pending_open
            and result.pending is None
            and CONFIRMATION_REQUEST_PATTERN.search(reply)
        ):
            warnings.append("warn:confirmation_without_pending")
```

Et les deux returns deviennent :

```python
        if reasons:
            return GuardResult(False, tuple(reasons), _safe_reply(result, self.today), tuple(warnings))
        return GuardResult(True, (), reply, tuple(warnings))
```

- [ ] **Step 4: Câbler le call site et la persistance**

(a) `backend/src/fitmas/runtime_v0/runtime.py` ligne 94, remplacer :

```python
    guarder = OutputGuard(snapshot.today)
```

par :

```python
    guarder = OutputGuard(snapshot.today, pending_open=snapshot.active_pending is not None)
```

(b) `backend/src/fitmas/runtime_v0/audit.py` ligne 77, remplacer :

```python
                json.dumps(guard.blocked_reasons, ensure_ascii=False),
```

par :

```python
                json.dumps([*guard.blocked_reasons, *guard.warnings], ensure_ascii=False),
```

(c) `backend/src/fitmas/runtime_v0/runtime.py`, dans `_existing_result` (~ligne 171), remplacer :

```python
    guard = GuardResult(bool(turn["guard_ok"]), tuple(json.loads(turn["guard_reasons_json"])), turn["reply"])
```

par :

```python
    stored_reasons = json.loads(turn["guard_reasons_json"])
    guard = GuardResult(
        bool(turn["guard_ok"]),
        tuple(reason for reason in stored_reasons if not reason.startswith("warn:")),
        turn["reply"],
        tuple(reason for reason in stored_reasons if reason.startswith("warn:")),
    )
```

- [ ] **Step 5: Vérifier que tout passe**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_guard.py tests/runtime_v0/test_runtime_flow.py tests/runtime_v0/test_result_reply.py -v`
Expected: tous PASS (le warning ne change jamais `ok` ni `guard_ok`).

- [ ] **Step 6: Commit**

```bash
git add backend/src/fitmas/runtime_v0/guard.py backend/src/fitmas/runtime_v0/runtime.py backend/src/fitmas/runtime_v0/audit.py tests/runtime_v0/test_guard.py
git commit -m "feat(runtime_v0): warn:confirmation_without_pending — promesse fantome instrumentee, jamais bloquante"
```

---

### Task 5: Compteur warning dans la matrix

**Files:**
- Modify: `scripts/v0_eval/run_matrix.py` (~ligne 552)
- Test: `tests/runtime_v0/test_v0_eval_scripts.py` (si un test d'agrégat existe — sinon vérification par run fake)

- [ ] **Step 1: Ajouter le compteur**

Dans `scripts/v0_eval/run_matrix.py`, dans le dict de résumé où vivent `raw_json_block_count` / `truncated_reply_count` (~ligne 552), ajouter :

```python
        "confirmation_without_pending_warn_count": guard_reasons.count("warn:confirmation_without_pending"),
```

- [ ] **Step 2: Vérifier par run fake**

Run: `.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1`
Expected: 11/11, `confirmation_without_pending_warn_count: 0` visible dans le résumé, danger metrics à 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/v0_eval/run_matrix.py
git commit -m "feat(v0_eval): compteur confirmation_without_pending_warn dans le resume matrix"
```

---

### Task 6: Persona couche 2 « fil de proposition »

**Files:**
- Modify: `scripts/v0_eval/probe_live_simulation.py` (liste `PERSONAS` ~ligne 52, et le bloc de verdict mécanique ~lignes 244-264)

- [ ] **Step 1: Lire le bloc existant**

Lire `scripts/v0_eval/probe_live_simulation.py` en entier — en particulier la structure des dicts `PERSONAS` (`key`, `title`, `opener`, `persona`) et le bloc de garanties dures spécifique `if persona["key"] == "blessure":` (~lignes 244-262, requêtes DB incluses). Le nouveau persona suit exactement ces patterns.

- [ ] **Step 2: Ajouter le persona**

Dans `PERSONAS`, ajouter :

```python
    {
        "key": "fil",
        "title": "fil de proposition (confirmation anaphorique)",
        "opener": "Mince j'ai loupé ma séance de hier, tu peux me la déplacer à demain ?",
        "persona": (
            "Tu es Loïc, coureur amateur, tu écris sur Telegram en messages courts. "
            "Tu as loupé ta séance d'hier et tu veux la décaler à demain. "
            "Au tour 2, exprime une préférence courte liée à ce que le coach vient de proposer "
            "(par exemple « j'aurais préféré un petit footing »), sans répéter ta demande initiale. "
            "Au tour 3, réponds UNIQUEMENT « c'est bien ça oui » — rien d'autre. "
            "Ne reformule jamais ta demande. Reste naturel et bref."
        ),
    },
```

- [ ] **Step 3: Ajouter les garanties dures du persona**

Dans `_run_persona`, à côté du bloc `if persona["key"] == "blessure":`, ajouter un bloc miroir pour `fil`. Garanties mécaniques (mêmes helpers DB que le bloc blessure) :

- au moins un artefact créé sur la conversation : un pending (`select count(*) from v0_pending_confirmations`) OU une command appliquée (`select count(*) from v0_command_events where status = 'applied'` hors bookkeeping) ;
- `guard_all_ok` reste vrai et danger metrics à 0 (déjà collectés par la sonde) ;
- le verdict juge LLM (déjà appelé pour chaque persona) évalue : le tour « c'est bien ça oui » a été rattaché au fil (pas de « je n'ai pas d'info », pas de redemande à zéro).

```python
        if persona["key"] == "fil":
            with connect(db_path) as connection:
                pending_count = connection.execute(
                    "select count(*) from v0_pending_confirmations"
                ).fetchone()[0]
                applied_count = connection.execute(
                    "select count(*) from v0_command_events where status = 'applied'"
                    " and command_type not in ('UpdateConversationStateCommand',)"
                ).fetchone()[0]
            ok = guard_all_ok and (pending_count > 0 or applied_count > 0)
```

Adapter les noms de variables locales (`db_path`, `guard_all_ok`, `ok`) à ceux réellement utilisés dans `_run_persona` — le bloc blessure montre la forme exacte.

- [ ] **Step 4: Mettre à jour l'aide CLI**

Dans le même fichier : la ligne `--persona` help et le message d'erreur listent `indispo | blessure | fun | all` → ajouter `fil`.

- [ ] **Step 5: Lancer la sonde (nécessite la clé DeepSeek dans .env)**

Run: `.venv/bin/python scripts/v0_eval/probe_live_simulation.py --provider deepseek --persona fil`
Expected: `PERSONA FIL: PASS` — le tour 3 est interprété comme la confirmation du fil (pending créé/résolu ou commit), jamais « je n'ai pas d'info » ; juge LLM favorable ; guard ok partout. Lancer 2x pour la stabilité (non-déterminisme provider).

- [ ] **Step 6: Commit**

```bash
git add scripts/v0_eval/probe_live_simulation.py
git commit -m "feat(v0_eval): persona fil — confirmation anaphorique prouvee couche 2"
```

---

### Task 7: Landing — cap LOC, suite complète, docs

**Files:**
- Modify: `tests/runtime_v0/test_import_boundaries.py` (cap + justification)
- Modify: `docs/RUNTIME-V0.md` (header/budget + raisons guard)
- Modify: `docs/BUILD-ORDER.md` (section Fait)

- [ ] **Step 1: Mesurer le LOC réel et bumper le cap**

Run: `.venv/bin/python -m pytest tests/runtime_v0/test_import_boundaries.py -v`

Si FAIL sur le cap : lire le chiffre réel dans le message d'assert, puis dans `tests/runtime_v0/test_import_boundaries.py` ajouter au bloc de commentaires :

```python
    # 4586 -> <chiffre réel> (12 juin 2026): mémoire court terme conversationnelle —
    # transcript verbatim des 4 derniers échanges (<=48h) dans le SnapshotHeader,
    # reconstruit read-only depuis v0_input_events x v0_turns ; + canal warnings du
    # guard (warn:confirmation_without_pending, jamais bloquant). Motivé par le
    # dogfood du 12 juin (fil de conversation mort à chaque tour). Capacité prouvée
    # couche 2 (probe_live_simulation persona fil).
    # Spec : docs/superpowers/specs/2026-06-12-mini-transcript-design.md.
```

et remplacer `assert loc <= 4586` par `assert loc <= <chiffre réel>`.

- [ ] **Step 2: Suite complète + matrix fake**

Run:
```bash
.venv/bin/python -m pytest tests/runtime_v0
.venv/bin/python scripts/v0_eval/run_matrix.py --provider fake --repetitions 1
```
Expected: tous les tests PASS ; matrix `11/11` ; danger metrics 0 ; guard fallback 0 %.

- [ ] **Step 3: Mettre à jour les docs**

`docs/RUNTIME-V0.md` :
- section « Voix Et Garde », tableau des raisons : ajouter une ligne `warn:confirmation_without_pending   (warning, jamais bloquant) reply demande confirmation sans pending ouvert ni créé` ;
- section « Boucle » ou juste après : une phrase sur le transcript (« le snapshot porte les 4 derniers échanges verbatim (≤48h) — mémoire court terme ; le moyen terme = facts/pendings ») ;
- section « Budget » : noter le bump avec le chiffre réel.

`docs/BUILD-ORDER.md`, section « Prochaine Tranche / Fait » : ajouter une entrée datée 12 juin 2026 (mini-transcript + métrique, motivé dogfood, prouvé couche 2 persona fil, spec `2026-06-12-mini-transcript-design.md`).

- [ ] **Step 4: Commit final**

```bash
git add tests/runtime_v0/test_import_boundaries.py docs/RUNTIME-V0.md docs/BUILD-ORDER.md
git commit -m "docs+cap: landing mini-transcript — memoire court terme prouvee couche 2"
```

---

## Self-Review (fait à l'écriture du plan)

- **Couverture spec** : §1 transcript → Tasks 1-3 ; §2 métrique → Tasks 4-5 ; §3 preuve couche 1 → steps de test des Tasks 1-4, couche 2 → Task 6 ; §4 budget → Task 7. Hors-scope respecté (pas de résumé, pas de chemin « séance passée »).
- **Placeholders** : Task 6 Step 3 demande une adaptation aux noms locaux de `_run_persona` — assumé et borné (le bloc blessure existant est la référence exacte dans le même fichier).
- **Cohérence types** : `TranscriptEntry(role, text, at)` identique Tasks 1-2 ; `GuardResult(ok, blocked_reasons, sanitized_reply, warnings)` identique Task 4 ; `build(user_id, now, current_event_id)` identique Tasks 1 et 3.
