---
summary: spec complète du prototype Runtime V0 — agent LLM + tools bornés + proposal + policy + executor déterministe
read_when:
  - implémenter le prototype runtime_v0
  - comprendre la cible architecturale du test V0
  - mesurer si la 3e voie (LLM propose + backend valide) corrige les bugs structurels
  - challenger une PR runtime_v0
---

# Runtime V0 — Spec d'implémentation

> **Important pour l'agent implémenteur** : ce document est self-contained. Il décrit *tout* ce qu'il faut savoir pour coder le prototype. Ne pas modifier le code existant hors de `runtime_v0/`. Ne pas migrer la prod. C'est un test isolé.

---

## 0. Contexte produit (lecture obligatoire)

FitMAS est un coach IA multisport qui ajuste l'entraînement selon la vraie vie. Stack : FastAPI + SQLite + SQLAlchemy 2.0 + Anthropic Claude (et autres providers) + Telegram bot + webapp React.

Le runtime actuel est en cours de refactor depuis plusieurs mois. Malgré le refactor, des bugs structurels persistent en dogfood multi-provider :

- **Bug A — vieux plan** : le coach ressort un plan obsolète (ex: du 7-14 mai) au lieu du plan actuel
- **Bug B — mauvaise correction d'exécution** : quand l'utilisateur dit "en fait j'ai fait la séance", le coach corrige la mauvaise séance ou reste bloqué
- **Bug C — follow-up cassé** : quand l'utilisateur dit "déplace ça à vendredi" puis "la séance de récup", le coach perd le contexte de la 1ère demande

Ces bugs sont partagés entre providers (DeepSeek, Gemini, Claude). Ce n'est pas un bug de modèle — c'est un bug d'interface entre backend et LLM.

**Le V0 teste une hypothèse** : un runtime *agent + tools + proposal + policy + executor* corrige-t-il ces bugs structurellement ?

---

## 1. Objectif du V0

Une seule question à laquelle V0 doit répondre :

> Sur 5 scénarios précis × 3 providers × 3 répétitions = 45 runs, est-ce que le nouveau runtime obtient ≥90 % de succès, 0 wrong write, 0 vieux plan ressorti, 0 mauvaise correction ?

Si OUI → migration progressive de la prod sur ce runtime.
Si NON → analyse des fails, raffinement ou retour à l'architecture actuelle.

**Le V0 n'est pas un produit fini. C'est une preuve d'architecture.**

---

## 2. Scope strict

### Ce qu'on code

- Un runtime isolé dans `backend/src/fitmas/runtime_v0/`
- 1 endpoint API isolé `POST /v0/message` (pas branché sur Telegram en V0)
- 10 tools (5 read + 4 propose + 1 clarification)
- 6 types de commands
- 5 scénarios reproductibles + oracle pour chacun
- 1 script matrix `scripts/v0_eval/run_matrix.py`
- DB séparée `fitmas_v0.db`

### Ce qu'on NE code PAS en V0

- Pas de heartbeat / proactivité (V0 = user_message only)
- Pas de Mode 2 / Coach analysis multi-tour profond
- Pas de `propose_goal_change` (hors scope des 5 scénarios)
- Pas de shadow mode agent pur (phase 2)
- Pas de LLM judge dans OutputGuard (déterministe only en V0)
- Pas de 2 modes ReplyComposer (LLM only)
- Pas de replan complet
- Pas de periodization long terme
- Pas de migration prod
- Pas de modification du code hors `runtime_v0/`
- Pas de write tool low-stakes direct (tout passe par propose en V0)

---

## 3. Architecture

```text
                  ┌────────────────────┐
                  │     InputEvent      │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │   WorldSnapshot     │
                  │ (header + tools)    │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │    CoachAgent       │
                  │ LLM + tools bornés  │
                  │ max_steps=3         │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │  ActionProposal     │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │  RuntimePolicy      │
                  │ commit/pending/     │
                  │ block/clarify       │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │  CommandExecutor    │
                  │ (seul write)        │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │   RuntimeResult     │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │  ReplyComposer      │
                  │ (LLM, contrat strict)│
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │   OutputGuard       │
                  │ (déterministe)      │
                  └─────────┬──────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │      Audit          │
                  │ (rejouable)         │
                  └────────────────────┘
```

**Phrase clé** : *Le LLM choisit l'action. Le backend choisit si cette action devient réelle.*

---

## 4. Structure de dossier

```text
backend/src/fitmas/runtime_v0/
  __init__.py
  event.py              # InputEvent
  snapshot.py           # WorldSnapshot, SnapshotHeader, builder
  state.py              # ConversationState
  proposals.py          # ActionProposal + drafts
  agent.py              # CoachAgent (tool loop)
  tools_read.py         # 5 read tools
  tools_proposal.py     # 4 propose + 1 ask_clarification
  tool_catalog.py       # mapping event.type → tools autorisés
  policy.py             # RuntimePolicy + règles V0
  executor.py           # CommandExecutor + Commands
  result.py             # RuntimeResult builder
  reply.py              # ReplyComposer (LLM)
  guard.py              # OutputGuard (déterministe)
  audit.py              # Persistence + replay
  idempotency.py        # Lock par event.id
  db.py                 # SQLite fitmas_v0.db schema + session
  api.py                # POST /v0/message endpoint
  prompts/
    coach_system.py     # System prompt CoachAgent (<150 lignes)
    reply_system.py     # System prompt ReplyComposer (<80 lignes)
  scenarios.py          # 5 ScenarioOracle

backend/src/fitmas/tests/runtime_v0/
  test_snapshot.py
  test_agent_tool_loop.py
  test_policy_rules.py
  test_executor.py
  test_guard.py
  test_scenario_1_current_plan.py
  test_scenario_2_tomorrow.py
  test_scenario_3_skipped_yesterday.py
  test_scenario_4_correction.py
  test_scenario_5_followup.py

scripts/v0_eval/
  run_matrix.py         # 5 scénarios × 3 providers × 3 répétitions
  oracle_compare.py     # compare run output vs oracle
  report.py             # markdown report avec mesures
```

**Règle d'isolation absolue** : `runtime_v0/` n'importe RIEN depuis `backend/src/fitmas/decision/`, `domain/`, `llm/`, `skills/`, `tools/`, `app/`. Il peut importer depuis `core/` uniquement pour timezone/temps.

Si un besoin pousse à importer du code existant, c'est qu'on n'est pas en V0 isolé — re-écrire le code dans `runtime_v0/` (même si redondant).

---

## 5. Doctrine non-négociable

Ces règles dépassent V0 — elles viennent de la doctrine FitMAS et s'appliquent au V0 sans exception :

1. **Pas de regex / keywords sur texte utilisateur libre.** Toute compréhension du texte user passe par le LLM via tools/proposal. Jamais un `if "demain" in text:`.
2. **Pas de write DB hors `CommandExecutor`.** Aucun service, aucun tool, aucun helper n'écrit dans `fitmas_v0.db` directement.
3. **Pas de claim "j'ai fait X" sans `CommandEvent` correspondant.** Vérifié par `OutputGuard`.
4. **Pas de fallback local qui parle.** Si LLM échoue, `no_send` propre + audit, pas de réponse "improvisée" par un helper.
5. **Pas d'historique non borné injecté dans le prompt.** `WorldSnapshot` est borné dur.
6. **Pas de mutation de la prod en V0.** DB séparée. Endpoint séparé. Aucun side-effect sur Telegram, app, ou fitmas.db.

---

## 6. Types centraux

### 6.1 `InputEvent`

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

@dataclass(frozen=True)
class InputEvent:
    id: str                    # UUID, fourni par le caller
    user_id: int
    source: Literal["telegram", "app", "scheduler", "test"]
    type: Literal[
        "user_message",
        "heartbeat_tick",          # réservé V0, non géré
        "activity_imported",       # réservé V0, non géré
        "session_missed_detected", # réservé V0, non géré
    ]
    text: str | None
    payload: dict[str, Any]
    occurred_at: datetime
```

**V0 ne gère que `type == "user_message"`.** Les autres types sont définis pour la cible long terme mais retournent `no_send` proper en V0.

### 6.2 `WorldSnapshot` et `SnapshotHeader`

```python
from datetime import date

@dataclass(frozen=True)
class SessionView:
    id: int
    date: date
    sport: str
    title: str
    duration_min: int
    intensity_label: str  # "easy", "tempo", "vma", "long", "recovery", etc.
    priority: Literal["key", "secondary", "optional"]
    status: Literal["planned", "done", "skipped", "partial"]

@dataclass(frozen=True)
class ActivityView:
    id: int
    date: date
    sport: str
    duration_min: int
    distance_km: float | None
    notes: str | None
    source: Literal["strava", "manual"]

@dataclass(frozen=True)
class FactView:
    id: int
    kind: Literal["preference", "health", "availability", "constraint", "goal"]
    text: str
    confidence: float
    created_at: datetime
    expires_at: datetime | None

@dataclass(frozen=True)
class PendingView:
    id: int
    type: str
    summary: str
    expires_at: datetime

@dataclass(frozen=True)
class CommandEventView:
    id: int
    type: str
    target_session_id: int | None
    status: Literal["applied", "blocked"]
    summary: str
    created_at: datetime

@dataclass(frozen=True)
class WorldSnapshot:
    user_id: int
    today: date
    now: datetime
    timezone: str

    objective: str | None

    current_plan: tuple[SessionView, ...]       # today → today+14, BORNE DURE
    recent_plan: tuple[SessionView, ...]        # today-7 → today-1
    recent_activities: tuple[ActivityView, ...] # today-21 → today

    active_facts: tuple[FactView, ...]
    active_pending: PendingView | None

    recent_execution_events: tuple[CommandEventView, ...]
    recent_plan_events: tuple[CommandEventView, ...]

    conversation_state: "ConversationState"

    def header(self) -> "SnapshotHeader":
        """Version compacte pour injection dans le prompt système."""
        ...
```

**Règle dure WorldSnapshot** :
- `current_plan` borné à 14 jours futurs maximum
- `recent_plan` borné à 7 jours passés maximum
- `recent_activities` borné à 21 jours passés maximum
- `active_facts` borné à 10 facts max (les plus récents non expirés)
- `recent_execution_events` et `recent_plan_events` bornés à 5 chacun

Si un de ces caps est dépassé dans le builder → AssertionError. Pas de "petite exception" tolérée.

### 6.3 `SnapshotHeader` (ce qui est injecté dans le prompt)

```python
@dataclass(frozen=True)
class SnapshotHeader:
    today: date
    timezone: str
    objective: str | None
    next_3_sessions: tuple[SessionView, ...]      # max 3
    active_facts_summary: tuple[str, ...]         # max 5 strings courtes
    pending: PendingView | None
    last_unresolved_intent: dict | None
    last_execution_event: CommandEventView | None

    def to_prompt_text(self) -> str:
        """Sérialise en bloc texte compact, <500 tokens."""
        ...
```

**Budget tokens header** : ≤500 tokens. Si dépassement, c'est qu'un champ doit devenir accessible par tool, pas par injection.

### 6.4 `ConversationState`

```python
@dataclass(frozen=True)
class ConversationState:
    last_unresolved_intent: dict[str, Any] | None
    last_execution_event_id: int | None
    last_pending_id: int | None
    last_user_turn_id: int | None
    expires_at: datetime | None
```

Exemple `last_unresolved_intent` :

```json
{
  "type": "move_session",
  "target_date": "2026-05-29",
  "missing": ["source_ref"],
  "captured_at": "2026-05-22T14:30:00+02:00"
}
```

**TTL** : `expires_at = captured_at + 24h`. Au-delà, ignoré.

### 6.5 `ActionProposal` et drafts

```python
@dataclass(frozen=True)
class MemoryFactDraft:
    kind: Literal["preference", "health", "availability", "constraint"]
    text: str
    confidence: float
    expires_at: datetime | None

@dataclass(frozen=True)
class ExecutionUpdateDraft:
    session_id: int
    status: Literal["done", "skipped", "partial"]
    duration_min: int | None = None
    intensity_note: str | None = None
    evidence: str = ""

@dataclass(frozen=True)
class ExecutionCorrectionDraft:
    previous_event_id: int                # OBLIGATOIRE
    correct_session_id: int
    correct_status: Literal["done", "skipped", "partial", "planned"]
    duration_min: int | None = None
    intensity_note: str | None = None
    evidence: str = ""

@dataclass(frozen=True)
class PlanPatchDraft:
    operations: tuple["PlanPatchOperation", ...]
    rationale: str

@dataclass(frozen=True)
class PlanPatchOperation:
    kind: Literal["move", "swap", "lighten", "replace", "remove_optional"]
    source_session_id: int
    target_date: date | None = None
    target_session_id: int | None = None  # pour swap
    new_intensity_label: str | None = None  # pour lighten/replace
    new_sport: str | None = None  # pour replace
    new_duration_min: int | None = None

@dataclass(frozen=True)
class ActionProposal:
    type: Literal[
        "answer",
        "ask_clarification",
        "memory_update",
        "execution_update",
        "execution_correction",
        "plan_patch",
        "no_send",
    ]

    confidence: float
    user_intent_summary: str
    evidence: tuple[str, ...]

    # Selon le type, un seul de ces champs est rempli
    answer_facts: tuple[str, ...] = ()
    clarification_question: str | None = None
    memory_updates: tuple[MemoryFactDraft, ...] = ()
    execution_update: ExecutionUpdateDraft | None = None
    execution_correction: ExecutionCorrectionDraft | None = None
    plan_patch: PlanPatchDraft | None = None
```

**Pas de `draft_reply` dans `ActionProposal`** en V0. La reply est générée après par `ReplyComposer` à partir de `RuntimeResult`.

### 6.6 `PolicyDecision`

```python
@dataclass(frozen=True)
class PolicyDecision:
    action: Literal[
        "allow_commit",
        "create_pending",
        "block",
        "ask_clarification",
        "answer_only",
        "no_send",
    ]
    reason: str
    risk_level: Literal["low", "medium", "high"]
    commands: tuple["Command", ...]
    reply_facts: tuple[str, ...]  # facts à injecter dans la reply
```

### 6.7 `Command` et `CommandEvent`

```python
from abc import ABC

class Command(ABC):
    """Marker base class."""
    pass

@dataclass(frozen=True)
class SetSessionStatusCommand(Command):
    session_id: int
    status: Literal["done", "skipped", "partial", "planned"]
    duration_min: int | None
    intensity_note: str | None
    evidence: str

@dataclass(frozen=True)
class CorrectSessionStatusCommand(Command):
    previous_event_id: int
    session_id: int
    status: Literal["done", "skipped", "partial", "planned"]
    duration_min: int | None
    intensity_note: str | None
    evidence: str

@dataclass(frozen=True)
class ApplyPlanPatchCommand(Command):
    operations: tuple[PlanPatchOperation, ...]
    rationale: str

@dataclass(frozen=True)
class CreatePendingConfirmationCommand(Command):
    type: str
    summary: str
    payload_json: str
    expires_at: datetime

@dataclass(frozen=True)
class UpsertMemoryFactCommand(Command):
    kind: str
    text: str
    confidence: float
    expires_at: datetime | None

@dataclass(frozen=True)
class UpdateConversationStateCommand(Command):
    last_unresolved_intent: dict | None
    last_execution_event_id: int | None
    last_pending_id: int | None

@dataclass(frozen=True)
class CommandEvent:
    id: int
    turn_id: str
    command_type: str
    target_type: str           # "session", "fact", "pending", "state"
    target_id: str             # str pour homogénéité
    status: Literal["applied", "blocked"]
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str
    created_at: datetime
```

### 6.8 `RuntimeResult`

```python
@dataclass(frozen=True)
class ReplyContract:
    must_include: tuple[str, ...]      # facts obligatoires
    must_not_claim: tuple[str, ...]    # interdits ("j'ai déplacé" si pas committed)
    tone: Literal["informative", "confirming", "asking", "explaining_block"]
    max_sentences: int

@dataclass(frozen=True)
class RuntimeResult:
    event_id: str
    turn_id: str
    proposal_type: str
    policy_action: str

    committed_events: tuple[CommandEvent, ...]
    blocked_reasons: tuple[str, ...]
    pending: PendingView | None

    read_facts: tuple[str, ...]
    reply_contract: ReplyContract
```

---

## 7. Tools (10 au total)

### 7.1 Read tools (5)

```python
def get_current_plan(days: int = 7) -> dict:
    """
    Returns:
        {
            "today": "2026-05-22",
            "timezone": "Europe/Paris",
            "sessions": [
                {"id": 66, "date": "2026-05-22", "sport": "run", "title": "...", ...},
                ...
            ]
        }
    Borne dure: days ∈ [1, 14]. Si days > 14, clipped à 14.
    """

def get_plan_day(date: str) -> dict:
    """
    date format: "YYYY-MM-DD"
    Borne: date doit être dans [today-7, today+14], sinon erreur.
    """

def get_session(session_id: int) -> dict:
    """
    Returns détails d'une session. Erreur si non trouvée.
    """

def get_recent_execution_events(limit: int = 5) -> dict:
    """
    Returns les N derniers CommandEvent de type Set/CorrectSessionStatus.
    Borne: limit ∈ [1, 10].
    """

def get_active_facts() -> dict:
    """
    Returns les facts non expirés, triés par created_at desc.
    """
```

### 7.2 Proposal tools (4) + clarification (1)

```python
def propose_execution_update(
    session_id: int,
    status: str,
    duration_min: int | None = None,
    intensity_note: str | None = None,
    evidence: str = "",
) -> dict:
    """
    Ne commit jamais. Retourne ActionProposal sérialisée.
    """

def propose_execution_correction(
    previous_event_id: int,   # OBLIGATOIRE
    correct_session_id: int,
    correct_status: str,
    duration_min: int | None = None,
    intensity_note: str | None = None,
    evidence: str = "",
) -> dict:
    """
    Ne commit jamais. `previous_event_id` doit exister dans recent_execution_events
    sinon Policy block.
    """

def propose_plan_patch(
    operations: list[dict],
    rationale: str,
) -> dict:
    """
    operations: list of {kind, source_session_id, ...}
    Ne commit jamais.
    """

def propose_memory_update(
    kind: str,
    text: str,
    confidence: float,
    expires_at: str | None = None,
) -> dict:
    """
    kind ∈ {"preference", "health", "availability", "constraint"}
    Ne commit jamais.
    """

def ask_clarification(question: str) -> dict:
    """
    Termine le tour avec ActionProposal(type="ask_clarification").
    Le backend persistera last_unresolved_intent automatiquement à partir
    du dernier proposal tool tenté (si présent en mémoire de tour).
    """
```

### 7.3 `tool_catalog.for_event`

```python
def for_event(event: InputEvent, snapshot: WorldSnapshot) -> list[Tool]:
    """
    V0: pour user_message, retourne TOUS les tools (10).
    Plus tard: filtrage selon event.type (heartbeat = read-only + propose limité).
    """
```

---

## 8. CoachAgent

### 8.1 Boucle

```python
class CoachAgent:
    def __init__(self, llm_client: LLMClient, system_prompt: str):
        ...

    def run(
        self,
        event: InputEvent,
        snapshot_header: SnapshotHeader,
        tools: list[Tool],
        max_steps: int = 3,
    ) -> ActionProposal:
        """
        1. Construit messages avec system_prompt + header + user text
        2. Loop:
           - Appelle LLM avec tools
           - Si tool_call → exécute (read) ou capture (proposal)
           - Si proposal tool appelé → retourne ActionProposal correspondante
           - Si pas de tool_call et juste du texte → ActionProposal(type="answer", ...)
        3. Après max_steps sans proposal → ActionProposal(type="no_send", reason="max_steps_reached")
        """
```

### 8.2 Règles tool loop

- `max_steps=3` par défaut
- Si LLM appelle un tool inexistant → tool_result error + 1 retry max
- Si LLM produit JSON invalide pour tool args → 1 retry max avec error message
- Si LLM appelle 2 proposal tools dans le même message → garde le premier, ignore le second
- Si après 3 steps pas de proposal explicite et pas de texte d'answer → `no_send` propre

### 8.3 System prompt

Cap dur : **<150 lignes**. Structure obligatoire :

```text
1. Rôle (5 lignes)
   Tu es FitMAS, un coach IA sportif. Tu aides l'utilisateur à comprendre
   et adapter son plan d'entraînement.

2. Règles dures (10 lignes)
   - Tu ne dis jamais "j'ai fait X" sans avoir appelé un propose_X tool.
   - Tu utilises get_current_plan pour parler du plan, jamais ta mémoire.
   - Les dates dans le snapshot sont la vérité absolue.
   - Si tu manques d'information, appelle un read tool ou ask_clarification.

3. World view (15 lignes)
   Tu reçois un snapshot header avec: today, objective, 3 prochaines séances,
   facts actifs, pending, last_unresolved_intent.
   Pour plus de détails: utilise les read tools.

4. Tools disponibles (40 lignes max — 4 lignes par tool)
   - get_current_plan(days=7): retourne le plan today→today+days
   - ...

5. Contrat de sortie (10 lignes)
   Tu finis ton tour par UN appel de proposal tool OU une réponse texte
   directe (cas "answer"). Jamais 2 propositions.

6. Exemples (40 lignes — 2 exemples one-shot courts)
   Ex 1: user "plan actuel" → tu appelles get_current_plan → tu finis avec texte
   Ex 2: user "j'ai pas fait hier" → get_recent_execution_events → propose_execution_update
```

**Si le system prompt dépasse 150 lignes, c'est de l'over-spec.** Casser en règles + déléguer aux exemples.

---

## 9. RuntimePolicy

### 9.1 Interface

```python
class RuntimePolicy:
    def evaluate(
        self,
        proposal: ActionProposal,
        snapshot: WorldSnapshot,
    ) -> PolicyDecision:
        ...
```

### 9.2 Règles V0 (dispatch sur `proposal.type`)

#### `type == "answer"`
```
action = "answer_only"
commands = ()
reply_facts = proposal.answer_facts  # facts à utiliser pour composer
```

#### `type == "ask_clarification"`
```
action = "ask_clarification"
commands = (
  UpdateConversationStateCommand(
    last_unresolved_intent = derive_from_recent_proposal_attempts(),
    ...
  ),
)
```

#### `type == "memory_update"`
```
for fact in proposal.memory_updates:
  - validate fact.kind ∈ allowed kinds
  - validate fact.confidence ∈ [0, 1]
  - validate fact.text non vide
  → allow_commit avec UpsertMemoryFactCommand
risk_level = "low"
```

#### `type == "execution_update"`
```
draft = proposal.execution_update
- validate draft.session_id existe dans recent_plan ∪ current_plan
- validate session.date ∈ [today-7, today+14]
- si conflit avec recent_execution_events (déjà un event sur cette session aujourd'hui)
  → ask_clarification "tu veux corriger l'event précédent ?"
- sinon → allow_commit avec SetSessionStatusCommand
risk_level = "low"
```

#### `type == "execution_correction"`
```
draft = proposal.execution_correction
- validate draft.previous_event_id ∈ recent_execution_events
- validate l'event ciblé est récent (<48h)
- validate draft.correct_session_id existe
- si validation OK → allow_commit avec CorrectSessionStatusCommand
- si previous_event_id introuvable → block, reason="event_not_found"
- si correct_session_id != event.target_session_id ET pas de raison explicite
  dans evidence → ask_clarification
risk_level = "medium"
```

#### `type == "plan_patch"`
```
draft = proposal.plan_patch
for op in draft.operations:
  - validate op.source_session_id existe dans current_plan
  - validate op.target_date ∈ [today, today+14] si présent
- si toutes ops touchent des sessions "optional" ou "secondary" ET 1 op seulement
  → allow_commit, risk_level="low"
- si touche 1 session "key" → create_pending, risk_level="medium"
- si touche >1 session → create_pending, risk_level="medium"
- si source_session_id introuvable → ask_clarification
- si conflit avec last_unresolved_intent → merge et résoudre
```

#### `type == "no_send"`
```
action = "no_send"
commands = ()
```

### 9.3 Garde-fous généraux

- `proposal.confidence < 0.5` ET `risk_level >= medium` → escalade en `create_pending` ou `ask_clarification`
- Plus de 3 commands dans une décision → block automatique (le V0 ne fait pas multi-action)

---

## 10. CommandExecutor

### 10.1 Interface

```python
class CommandExecutor:
    def __init__(self, session_factory):
        ...

    def execute(
        self,
        commands: tuple[Command, ...],
        turn_id: str,
    ) -> tuple[CommandEvent, ...]:
        """
        Exécute chaque command dans l'ordre. Pour chaque command:
        - lit before state
        - applique mutation
        - lit after state
        - crée CommandEvent (status=applied)
        Si une command lève une exception:
        - status=blocked, reason = str(exception)
        - les commands suivantes ne sont pas exécutées
        """
```

### 10.2 Règles

- **Append-only sur `command_events`**. Aucun UPDATE, aucun DELETE.
- **Transactional par command** : chaque command est dans sa propre transaction. Si la 2e échoue, la 1ère reste persistée.
- **Idempotent par `(turn_id, command_type, target_id)`** : si on rejoue le même turn (replay), on ne re-crée pas l'event.

### 10.3 Implémentation des commands

Chaque command a un handler dédié :

```python
def _apply_set_session_status(cmd: SetSessionStatusCommand, db) -> dict:
    """Returns (before_dict, after_dict). Lève si invalide."""

def _apply_correct_session_status(cmd: CorrectSessionStatusCommand, db) -> dict:
    """Idem. previous_event_id doit exister."""

# ... etc pour les 6 commands
```

---

## 11. ReplyComposer

### 11.1 Interface

```python
class ReplyComposer:
    def __init__(self, llm_client: LLMClient, system_prompt: str):
        ...

    def compose(
        self,
        result: RuntimeResult,
        snapshot: WorldSnapshot,
    ) -> str:
        """
        Génère une réponse texte à partir de result.
        Reçoit:
          - reply_contract (must_include, must_not_claim, tone, max_sentences)
          - committed_events
          - read_facts
          - pending si présent
        """
```

### 11.2 System prompt (<80 lignes)

```text
1. Rôle (3 lignes)
   Tu transformes un résultat de runtime en message coach humain et bref.

2. Règles dures (15 lignes)
   - Si committed_events est vide, n'écris jamais "j'ai fait", "j'ai déplacé", etc.
   - Si pending présent, demande explicitement confirmation.
   - Si blocked_reasons non vide, explique brièvement la raison.
   - Si answer_only, parle UNIQUEMENT depuis read_facts.
   - Pas de jargon: ne dis pas "policy", "commit", "candidate", "mutation", "runtime".
   - Pas de méta: ne dis pas "L'utilisateur demande...", "Option valide".
   - Max max_sentences phrases.
   - Tonalité: directe, sans flagornerie, type coach pragmatique.

3. Format input (10 lignes)
   Tu reçois un JSON avec: committed_events, read_facts, pending,
   blocked_reasons, reply_contract.

4. Exemples (40 lignes)
   ...
```

### 11.3 Règle de fallback

Si l'appel LLM échoue (timeout, error provider) :
- `result.policy_action == "answer_only"` → template court depuis `read_facts` (1ère phrase de chaque fact, max 3)
- Tout autre cas → reply = "Je n'ai pas pu finaliser la réponse. Réessaie dans un instant."
- Audit avec `reply_source = "fallback_template"`

---

## 12. OutputGuard (déterministe en V0)

```python
@dataclass(frozen=True)
class GuardResult:
    ok: bool
    blocked_reasons: tuple[str, ...]
    sanitized_reply: str  # si ok=False, fallback message

class OutputGuard:
    def verify(self, reply: str, result: RuntimeResult) -> GuardResult:
        """
        V0: règles déterministes uniquement. Pas de LLM judge.
        """
```

### 12.1 Règles V0

Bloque si :

1. **Claim non gagé** : reply contient pattern `(j'ai|j'ai bien|c'est) (déplacé|noté|enregistré|fait|modifié|appliqué)` ET `committed_events` vide → block
2. **Action sur pending** : reply contient "c'est fait" ou "appliqué" ET `pending` non null → block
3. **Jargon interne** : reply contient `(policy|backend|candidate|mutation|runtime|tool_call|proposal|snapshot)` (case insensitive) → block
4. **Méta** : reply commence par `(l'utilisateur|the user|option valide)` → block
5. **Date interdite** : `policy_action == "answer_only"` et reply contient une date qui n'est pas dans `read_facts` → block
6. **Vieux plan** : reply contient une date < `today - 7` jours → block (sauf si explicitement dans read_facts d'un correction)

Si bloqué : `sanitized_reply` = template safe générique selon le contexte.

### 12.2 Implémentation

Listes de patterns regex en constantes. Pas de NLP, pas de LLM. ~80 LOC.

---

## 13. Audit & DB

### 13.1 DB

Fichier : `fitmas_v0.db` à la racine (gitignored). Schéma SQLite minimal :

```sql
CREATE TABLE v0_input_events (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    text TEXT,
    payload_json TEXT NOT NULL,
    occurred_at TIMESTAMP NOT NULL
);

CREATE TABLE v0_turns (
    id TEXT PRIMARY KEY,            -- turn_id
    event_id TEXT NOT NULL REFERENCES v0_input_events(id),
    snapshot_json TEXT NOT NULL,    -- WorldSnapshot sérialisé complet
    proposal_json TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    reply TEXT NOT NULL,
    reply_source TEXT NOT NULL,     -- "llm" | "fallback_template"
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    guard_ok INTEGER NOT NULL,      -- 0/1
    guard_reasons_json TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE v0_command_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL REFERENCES v0_turns(id),
    command_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(turn_id, command_type, target_id)  -- idempotence
);

CREATE TABLE v0_scheduled_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date DATE NOT NULL,
    sport TEXT NOT NULL,
    title TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    intensity_label TEXT NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE v0_activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date DATE NOT NULL,
    sport TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    distance_km REAL,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE v0_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

CREATE TABLE v0_conversation_state (
    user_id INTEGER PRIMARY KEY,
    last_unresolved_intent_json TEXT,
    last_execution_event_id INTEGER,
    last_pending_id INTEGER,
    last_user_turn_id TEXT,
    expires_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE v0_pending_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE v0_idempotency_locks (
    event_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### 13.2 Replay

Une fonction `replay_turn(turn_id)` doit pouvoir :
1. Lire `v0_turns` row
2. Re-construire `WorldSnapshot` depuis `snapshot_json`
3. Re-jouer agent → policy → executor → reply → guard
4. Comparer output avec ce qui a été persisté

Utile pour debugger un fail multi-provider sans relancer le user-facing flow.

---

## 14. Idempotence

```python
def handle_event_idempotent(event: InputEvent) -> str:
    """
    1. Try INSERT into v0_idempotency_locks (event_id, turn_id=uuid4())
    2. If IntegrityError: fetch existing turn_id, return its reply
    3. Else: proceed with handle_event(event, turn_id)
    """
```

Garantit qu'un même `event.id` ne génère qu'un seul turn même si l'appelant retry.

---

## 15. Flow handle_event (pseudo-code complet)

```python
def handle_event(event: InputEvent) -> str:
    # 1. Idempotence
    turn_id = acquire_turn_lock(event.id)
    if existing := get_existing_reply(turn_id):
        return existing

    # 2. Snapshot
    snapshot = snapshot_builder.build(event.user_id, event.occurred_at)

    # 3. Si event.type != "user_message" en V0 → no_send
    if event.type != "user_message":
        result = no_send_result(event, turn_id, reason="event_type_not_supported_in_v0")
        return finalize(turn_id, event, snapshot, None, None, result, "")

    # 4. Agent
    tools = tool_catalog.for_event(event, snapshot)
    proposal = coach_agent.run(
        event=event,
        snapshot_header=snapshot.header(),
        tools=tools,
        max_steps=3,
    )

    # 5. Policy
    policy = runtime_policy.evaluate(proposal, snapshot)

    # 6. Executor
    command_events = command_executor.execute(policy.commands, turn_id)

    # 7. Result
    result = build_runtime_result(
        event=event,
        turn_id=turn_id,
        proposal=proposal,
        policy=policy,
        command_events=command_events,
    )

    # 8. Reply
    reply = reply_composer.compose(result, snapshot)

    # 9. Guard
    guard = output_guard.verify(reply, result)
    final_reply = reply if guard.ok else guard.sanitized_reply

    # 10. Audit
    audit.persist_turn(
        turn_id=turn_id,
        event=event,
        snapshot=snapshot,
        proposal=proposal,
        policy=policy,
        result=result,
        reply=final_reply,
        guard=guard,
    )

    return final_reply
```

Si cette fonction tient sur un écran, l'architecture est saine.

---

## 16. Les 5 scénarios + oracle

### 16.1 Structure `ScenarioOracle`

```python
@dataclass(frozen=True)
class CommandSpec:
    command_type: str
    target_type: str
    target_id: str | None = None  # None = wildcard
    expected_status: Literal["applied", "blocked"] = "applied"

@dataclass(frozen=True)
class ScenarioOracle:
    name: str
    description: str
    initial_db_state: dict          # seed pour fitmas_v0.db
    input_event: InputEvent
    expected_proposal_type: str
    expected_policy_action: str
    expected_commands: tuple[CommandSpec, ...]
    expected_reply_must_include: tuple[str, ...]
    expected_reply_must_not_contain: tuple[str, ...]
    max_acceptable_latency_ms: int = 8000
    max_acceptable_tokens: int = 4000
    followup: "ScenarioOracle | None" = None  # pour scénarios multi-tours
```

### 16.2 Les 5 oracles

#### Scénario 1 — Plan actuel
```python
ScenarioOracle(
    name="current_plan",
    description="User demande son plan actuel. Doit lister today→today+7 sans vieux plan.",
    initial_db_state={
        "today": "2026-05-22",
        "sessions": [
            # vieilles sessions (mai début) qui ne doivent PAS apparaître
            {"id": 10, "date": "2026-05-07", "sport": "run", ...},
            {"id": 11, "date": "2026-05-14", "sport": "bike", ...},
            # plan actuel
            {"id": 60, "date": "2026-05-22", "sport": "run", "title": "Footing récup", ...},
            {"id": 61, "date": "2026-05-24", "sport": "run", "title": "VMA courte", ...},
            {"id": 62, "date": "2026-05-26", "sport": "bike", "title": "Endurance", ...},
            # etc.
        ],
    },
    input_event=InputEvent(
        id="evt-1", user_id=1, source="test", type="user_message",
        text="Redonne-moi le plan actuel simplement, jour par jour.",
        payload={}, occurred_at=datetime(2026, 5, 22, 14, 0, tzinfo=ZoneInfo("Europe/Paris")),
    ),
    expected_proposal_type="answer",
    expected_policy_action="answer_only",
    expected_commands=(),
    expected_reply_must_include=("22", "24", "26"),  # dates présentes
    expected_reply_must_not_contain=("7 mai", "14 mai", "07/05", "14/05"),
)
```

#### Scénario 2 — Demain
```python
ScenarioOracle(
    name="tomorrow",
    description="User demande ce qu'il a demain. Ne doit parler QUE de demain.",
    initial_db_state=...,  # même base
    input_event=InputEvent(
        ..., text="J'ai quoi demain exactement ?",
        occurred_at=datetime(2026, 5, 22, 18, 0, ...),
    ),
    expected_proposal_type="answer",
    expected_policy_action="answer_only",
    expected_commands=(),
    expected_reply_must_include=("23",),  # date demain présente
    expected_reply_must_not_contain=("aujourd'hui", "22"),  # pas de today, pas de plan complet
)
```

#### Scénario 3 — J'ai pas fait hier
```python
ScenarioOracle(
    name="skipped_yesterday",
    description="User dit qu'il n'a pas fait la séance d'hier. Doit set status=skipped sur la bonne session.",
    initial_db_state={
        "today": "2026-05-22",
        "sessions": [
            {"id": 66, "date": "2026-05-21", "sport": "run", "title": "Footing", "status": "planned"},
            # etc.
        ],
    },
    input_event=InputEvent(
        ..., text="J'ai pas fait hier.",
        occurred_at=datetime(2026, 5, 22, 9, 0, ...),
    ),
    expected_proposal_type="execution_update",
    expected_policy_action="allow_commit",
    expected_commands=(
        CommandSpec(command_type="SetSessionStatusCommand", target_type="session", target_id="66"),
    ),
    expected_reply_must_include=("hier", "noté"),
    expected_reply_must_not_contain=("déplacé", "modifié", "appliqué"),
)
```

#### Scénario 4 — En fait je l'ai fait finalement
```python
ScenarioOracle(
    name="execution_correction",
    description="Après avoir dit skipped hier, user dit qu'il l'a fait finalement. Doit corriger l'event précédent.",
    initial_db_state={
        "today": "2026-05-22",
        "sessions": [
            {"id": 66, "date": "2026-05-21", "sport": "run", "status": "skipped"},
        ],
        "command_events": [
            {"id": 17, "command_type": "SetSessionStatusCommand", "target_id": "66", "status": "applied"},
        ],
    },
    input_event=InputEvent(
        ..., text="En fait j'ai fait la séance finalement, mais seulement 25 minutes tranquille.",
        occurred_at=datetime(2026, 5, 22, 10, 0, ...),
    ),
    expected_proposal_type="execution_correction",
    expected_policy_action="allow_commit",
    expected_commands=(
        CommandSpec(command_type="CorrectSessionStatusCommand", target_type="session", target_id="66"),
    ),
    expected_reply_must_include=("corrigé", "25"),
    expected_reply_must_not_contain=("nouvelle séance", "ajouté"),
)
```

#### Scénario 5 — Follow-up planning (2 tours)
```python
ScenarioOracle(
    name="followup_planning_turn1",
    description="User dit 'décale ça à vendredi' sans préciser quelle séance. Doit ask_clarification et stocker last_unresolved_intent.",
    initial_db_state={
        "today": "2026-05-22",  # mercredi → vendredi = 2026-05-24
        "sessions": [
            {"id": 60, "date": "2026-05-22", "sport": "run", "title": "Footing récup", "priority": "secondary"},
            {"id": 61, "date": "2026-05-23", "sport": "bike", "title": "Endurance", "priority": "secondary"},
            {"id": 62, "date": "2026-05-26", "sport": "run", "title": "VMA", "priority": "key"},
        ],
    },
    input_event=InputEvent(
        ..., id="evt-5a", text="Décale ça à vendredi.",
        occurred_at=datetime(2026, 5, 22, 15, 0, ...),
    ),
    expected_proposal_type="ask_clarification",
    expected_policy_action="ask_clarification",
    expected_commands=(
        CommandSpec(command_type="UpdateConversationStateCommand", target_type="state", target_id="1"),
    ),
    expected_reply_must_include=("quelle", "séance"),
    expected_reply_must_not_contain=("déplacé",),
    followup=ScenarioOracle(
        name="followup_planning_turn2",
        description="User précise: 'la séance de récup'. Doit merger avec last_unresolved_intent et propose_plan_patch.",
        initial_db_state=...,  # même base, après turn 1
        input_event=InputEvent(
            ..., id="evt-5b", text="Je parle de la séance de récup.",
            occurred_at=datetime(2026, 5, 22, 15, 1, ...),
        ),
        expected_proposal_type="plan_patch",
        expected_policy_action="allow_commit",  # session secondary, low risk
        expected_commands=(
            CommandSpec(command_type="ApplyPlanPatchCommand", target_type="session", target_id="60"),
        ),
        expected_reply_must_include=("déplacé", "vendredi"),
        expected_reply_must_not_contain=("VMA",),
    ),
)
```

### 16.3 Oracle compare

```python
def compare_run_to_oracle(
    turn_result: dict,    # ce qui a été persisté en v0_turns
    oracle: ScenarioOracle,
) -> RunVerdict:
    """
    Returns:
        RunVerdict(
            scenario=name,
            json_valid=bool,
            tool_sequence_valid=bool,
            proposal_type_match=bool,
            policy_action_match=bool,
            wrong_write_count=int,
            committed_when_should_block=bool,
            blocked_when_should_commit=bool,
            reply_claim_without_event=bool,
            reply_must_include_pass=bool,
            reply_must_not_contain_pass=bool,
            latency_ms=int,
            tokens=int,
            success=bool,  # all critical checks pass
        )
    """
```

---

## 17. Multi-provider matrix

### 17.1 Providers V0

```python
PROVIDERS_V0 = [
    {"name": "deepseek-chat", "client": "deepseek"},
    {"name": "claude-sonnet-4-5", "client": "anthropic"},
    {"name": "gemini-2.5-flash", "client": "gemini"},
]
```

(Grok et Mistral peuvent être ajoutés en phase 2 si bandwidth.)

### 17.2 Script `run_matrix.py`

```python
def run_matrix(repetitions: int = 3) -> Report:
    """
    Pour chaque (scénario, provider, repetition):
        1. Reset fitmas_v0.db avec initial_db_state
        2. Si followup: exécute turn 1, vérifie, puis turn 2
        3. Persist turn_result
        4. Compare via oracle_compare
    Génère report markdown:
        - tableau scenario × provider avec %success
        - latence p50/p95 par provider
        - tokens moyens par provider
        - liste des fails avec turn_id pour debug
    """
```

### 17.3 Mesures obligatoires

Par run :
- `json_valid` : la proposal est sérialisable
- `tool_sequence_valid` : pas plus de 3 steps, pas de tool inexistant
- `wrong_write_count` : nombre de CommandEvent.applied non listés dans expected_commands
- `committed_when_should_block` : bool
- `blocked_when_should_commit` : bool
- `reply_claim_without_event` : guard.blocked_reasons inclut "claim_without_event"
- `reply_must_include_pass` : tous les strings obligatoires présents
- `reply_must_not_contain_pass` : aucun string interdit présent
- `latency_p50_ms`, `latency_p95_ms`
- `tokens_in`, `tokens_out`

### 17.4 Critères de succès V0

| Métrique | Seuil |
|---|---|
| Success rate ≥ 90% sur DeepSeek | OUI/NON |
| Success rate ≥ 90% sur Claude | OUI/NON |
| Success rate ≥ 80% sur Gemini | OUI/NON (tolérance challenger) |
| `wrong_write_count` total sur les 45 runs | 0 |
| `reply_claim_without_event` total | 0 |
| Vieux plan détecté (date < today-7 dans reply) | 0 |
| `latency_p95_ms` sur user_message | < 8000 |

Si tous les seuils passent → V0 validé → migration progressive.

---

## 18. Discipline LOC budget

Budget total `runtime_v0/` (hors tests, hors scripts) : **≤ 2500 LOC**.

Estimation par module :

| Module | Cible LOC |
|---|---|
| `event.py` | 30 |
| `snapshot.py` | 250 |
| `state.py` | 50 |
| `proposals.py` | 150 |
| `agent.py` | 250 |
| `tools_read.py` | 200 |
| `tools_proposal.py` | 150 |
| `tool_catalog.py` | 50 |
| `policy.py` | 350 |
| `executor.py` | 350 |
| `result.py` | 100 |
| `reply.py` | 150 |
| `guard.py` | 100 |
| `audit.py` | 150 |
| `idempotency.py` | 50 |
| `db.py` | 100 |
| `api.py` | 70 |
| `prompts/coach_system.py` | 150 (texte) |
| `prompts/reply_system.py` | 80 (texte) |
| `scenarios.py` | 300 |
| **Total** | **~2330** |

Marge : ~170 LOC.

**Si un module dépasse 30% de sa cible → STOP, refactor avant de continuer.**

---

## 19. Anti-patterns explicites (ne pas faire)

1. ❌ **Ne pas importer depuis `decision/`, `domain/`, `llm/`, `skills/`, `tools/`, `app/`.** V0 est isolé.
2. ❌ **Ne pas ajouter de tool "à tout hasard".** Stick aux 10 définis.
3. ❌ **Ne pas écrire dans `fitmas.db` (prod).** Toujours `fitmas_v0.db`.
4. ❌ **Ne pas brancher le V0 sur Telegram en V0.** Endpoint `/v0/message` seulement.
5. ❌ **Ne pas mettre de logique métier dans `agent.py`.** L'agent est juste un loop LLM + tools.
6. ❌ **Ne pas faire de `if` sur le texte user dans le backend.** Le LLM décide via tools.
7. ❌ **Ne pas mettre `draft_reply` dans `ActionProposal`.** Reply générée après par `ReplyComposer`.
8. ❌ **Ne pas faire 2 modes ReplyComposer (template + LLM).** LLM only en V0.
9. ❌ **Ne pas appeler le LLM dans `OutputGuard`.** Déterministe only en V0.
10. ❌ **Ne pas ajouter de tool `commit_*` direct.** Tout passe par `propose_*` + Policy.
11. ❌ **Ne pas dépasser 150 lignes pour le system prompt CoachAgent.** Casser sinon.
12. ❌ **Ne pas dépasser 500 tokens pour `SnapshotHeader`.** Convertir un champ en tool sinon.
13. ❌ **Ne pas faire de transaction multi-command.** Chaque command est isolée.
14. ❌ **Ne pas faire UPDATE sur `v0_command_events`.** Append-only strict.
15. ❌ **Ne pas faire de fallback texte improvisé.** Si LLM échoue, template propre + audit.

---

## 20. Plan d'attaque 4 semaines

### Semaine 1 — Os du squelette
- Setup `runtime_v0/` + dossier tests
- DB schema `fitmas_v0.db` + migrations init
- `event.py`, `snapshot.py` (builder + header), `state.py`
- `tools_read.py` (5 tools) avec données mock
- `audit.py` minimal (persist turn)
- `idempotency.py`
- **Test E2E** : InputEvent → snapshot construit → audit persisté. Pas encore d'agent.

**Critère semaine 1** : `pytest tests/runtime_v0/test_snapshot.py` passe avec 5 cas (today, today+1, today+7, today+14 clipped, range vide).

### Semaine 2 — Agent + Proposal + Policy + Executor
- `proposals.py` (ActionProposal + tous les drafts)
- `agent.py` (tool loop, max_steps=3) — 1 seul provider (Claude) pour démarrer
- `tools_proposal.py` (4 propose + ask_clarification)
- `tool_catalog.py`
- `prompts/coach_system.py` (<150 lignes)
- `policy.py` (règles V0)
- `executor.py` (6 commands)
- **Tests** : scénario 1 (current_plan) + scénario 3 (skipped_yesterday) passent en local sur Claude.

**Critère semaine 2** : `pytest tests/runtime_v0/test_scenario_1_current_plan.py test_scenario_3_skipped_yesterday.py` passe sur Claude.

### Semaine 3 — Reply + Guard + scénarios complets
- `result.py` (RuntimeResult builder)
- `reply.py` (ReplyComposer)
- `prompts/reply_system.py` (<80 lignes)
- `guard.py` (déterministe)
- `scenarios.py` (5 oracles complets)
- `api.py` endpoint `/v0/message`
- **Tests** : tous les 5 scénarios passent sur Claude (incluant le followup du scénario 5).

**Critère semaine 3** : tous les `test_scenario_*.py` passent sur Claude. Audit replay fonctionne.

### Semaine 4 — Multi-provider + verdict
- Ajout providers DeepSeek et Gemini (juste config + adapters)
- `scripts/v0_eval/run_matrix.py`
- `scripts/v0_eval/oracle_compare.py`
- `scripts/v0_eval/report.py`
- Lancement matrix : 5 × 3 × 3 = 45 runs
- Rapport markdown généré : `docs/RUNTIME-V0-VERDICT.md`
- **Décision** : si critères de succès passent → migration. Sinon → analyse fails.

**Critère semaine 4** : rapport `RUNTIME-V0-VERDICT.md` généré avec verdict explicite.

---

## 21. Endpoint API V0

```python
# api.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/v0")

class V0MessageIn(BaseModel):
    user_id: int
    text: str
    event_id: str | None = None  # auto-uuid si absent

class V0MessageOut(BaseModel):
    turn_id: str
    reply: str
    proposal_type: str
    committed_event_count: int
    blocked: bool
    pending_id: int | None

@router.post("/message", response_model=V0MessageOut)
def post_message(payload: V0MessageIn) -> V0MessageOut:
    event = InputEvent(
        id=payload.event_id or str(uuid4()),
        user_id=payload.user_id,
        source="app",
        type="user_message",
        text=payload.text,
        payload={},
        occurred_at=datetime.now(UTC),
    )
    reply = handle_event(event)
    # ... fetch turn pour metadata
    return V0MessageOut(...)
```

Branché dans `backend/src/fitmas/api.py` derrière un flag d'env `FITMAS_V0_ENABLED=1` (off par défaut).

---

## 22. Configuration providers

Variables d'env à supporter :

```bash
ANTHROPIC_API_KEY=...
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...

FITMAS_V0_DB_PATH=./fitmas_v0.db
FITMAS_V0_DEFAULT_PROVIDER=claude-sonnet-4-5
FITMAS_V0_ENABLED=1
```

Adapter chaque provider derrière une interface `LLMClient` unifiée :

```python
class LLMClient(Protocol):
    def chat_with_tools(
        self,
        system: str,
        messages: list[dict],
        tools: list[ToolSchema],
    ) -> LLMResponse:
        ...
```

Implémentations : `AnthropicClient`, `DeepSeekClient`, `GeminiClient` dans `runtime_v0/llm_clients/` (à ajouter si trop gros pour `agent.py`).

---

## 23. Critères de done par composant

Avant de marquer un composant comme done, vérifier :

### `snapshot.py`
- [ ] Borne dure 14 jours futurs respectée (assertion)
- [ ] `SnapshotHeader.to_prompt_text()` produit ≤ 500 tokens (mesure tiktoken)
- [ ] Test : snapshot avec 50 sessions futures retourne 14 jours max
- [ ] Test : `last_unresolved_intent` expiré (>24h) absent du header

### `agent.py`
- [ ] `max_steps=3` respecté (test avec mock LLM qui boucle)
- [ ] Tool inexistant → 1 retry max puis no_send
- [ ] JSON invalide → 1 retry max puis no_send
- [ ] 2 proposal tools dans un message → garde le 1er

### `policy.py`
- [ ] Chaque branche de `proposal.type` testée
- [ ] Test : `confidence < 0.5` + risk medium → escalade
- [ ] Test : >3 commands → block

### `executor.py`
- [ ] Append-only strict (test : pas de UPDATE sur command_events)
- [ ] Idempotence par `(turn_id, command_type, target_id)`
- [ ] Transaction par command isolée

### `guard.py`
- [ ] Les 6 règles couvertes par test unitaire
- [ ] Pas d'appel LLM (test : mock LLM ne doit pas être appelé)

### `scenarios.py`
- [ ] Les 5 oracles complets et exécutables
- [ ] Scénario 5 followup fonctionne (2 tours chainés)

### Verdict global
- [ ] Matrix 45 runs lancée
- [ ] `RUNTIME-V0-VERDICT.md` généré
- [ ] Décision migration / no-go explicitement actée

---

## 24. La phrase à garder en tête

> Un LLM agentique lit un monde borné, utilise des tools simples, propose une action typée, puis un runtime strict décide si elle devient réelle.

Si une décision d'implémentation s'éloigne de cette phrase, c'est probablement la mauvaise décision pour V0.

---

## 25. Questions à poser AVANT d'implémenter (et pas après)

Si l'agent implémenteur rencontre une de ces ambiguïtés, demander à l'humain :

1. Quel modèle exact pour Claude/DeepSeek/Gemini ? (version, endpoint)
2. Faut-il un seed user automatique dans `fitmas_v0.db` ou attendre une commande seed explicite ?
3. Faut-il un script de reset de DB entre runs de la matrix ou réinit complète à chaque fois ?
4. Faut-il logger les tokens consommés cumulés sur la matrix pour budget cost ?
5. Pour le scénario 5 followup, est-ce que les 2 tours doivent être dans la même transaction Pytest ou 2 tests chaînés ?

**Toute autre ambiguïté : faire le choix le plus simple et noter dans un commentaire `# V0 choice: ...`**

---

## 26. Livrables finaux V0

À la fin de la semaine 4, l'agent implémenteur doit livrer :

1. `backend/src/fitmas/runtime_v0/` complet, ≤ 2500 LOC
2. `backend/src/fitmas/tests/runtime_v0/` avec tests verts sur 1 provider (Claude)
3. `scripts/v0_eval/run_matrix.py` + `oracle_compare.py` + `report.py`
4. `docs/RUNTIME-V0-VERDICT.md` avec le résultat de la matrix 45 runs
5. Un commit final avec le verdict :
   - Si succès : "V0 verdict: PASS — recommend migration phase A"
   - Si échec : "V0 verdict: FAIL — analysis of 12 failed runs in VERDICT.md"

---

## 27. Hors scope explicite (ne pas implémenter même si tentant)

- Heartbeat / cron / proactivité
- Mode "Coach analysis" multi-tour profond
- `propose_goal_change`
- Shadow mode agent pur (phase 2)
- LLM judge dans OutputGuard
- 2 modes ReplyComposer (template + LLM)
- Streaming LLM
- Telegram delivery
- Webapp UI pour V0
- Migration de données depuis `fitmas.db`
- Compatibilité descendante avec l'archi existante
- Renaming / refactor de fichiers hors `runtime_v0/`

---

**Fin de spec.** Si une section semble incomplète ou contradictoire, c'est un bug de spec — remonter à l'humain avant d'improviser.
