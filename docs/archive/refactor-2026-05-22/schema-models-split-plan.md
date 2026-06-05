---
summary: plan de coupe pour supprimer les monolithes root schema.py et models.py
read_when:
  - supprimer backend/src/fitmas/schema.py
  - supprimer backend/src/fitmas/models.py
  - modifier les contrats Pydantic ou les modeles ORM SQLAlchemy
  - verifier que root ne contient plus que les entrypoints
---

# Schema / Models Split Plan

## Objectif

Supprimer les deux derniers monolithes root non-entrypoint :

```text
backend/src/fitmas/models.py
backend/src/fitmas/schema.py
```

But produit : repo plus petit, frontieres plus nettes, moins de dependances
transverses.

Non-but : deplacer 800 lignes pour faire joli.

## Etat Actuel

Apres 13F :

```text
models.py  = supprime
schema.py  = supprime
root files = 3 (__init__.py, api.py, main.py)
```

Les contrats Pydantic sont maintenant repartis par owner :

```text
decision/message_models.py
domain/planning/view_models.py
domain/athlete/view_models.py
domain/execution/view_models.py
domain/memory/view_models.py
app/api/read_models.py
app/api/payloads.py
app/api/onboarding_models.py
```

Les records ORM SQLAlchemy sont maintenant repartis sous :

```text
core/orm/user.py
core/orm/memory.py
core/orm/execution.py
core/orm/integrations.py
core/orm/planning.py
core/orm/coaching.py
core/orm/athlete.py
```

## Diagnostic Initial

Etat initial :

```text
schema.py  = 547 lignes, 23 classes ORM SQLAlchemy, 68 imports actifs
models.py  = 258 lignes, 21 contrats Pydantic/Enum, 28 imports actifs
root files = 5
```

Risque principal :

```text
schema.py enregistre toutes les tables SQLAlchemy via Base.metadata.
Un split naif peut casser les relationships, l'ordre d'import ou init_db().
```

Decision :

```text
1. Supprimer models.py d'abord. Fait en 13C.
2. Supprimer schema.py ensuite. Fait en 13F.
3. Garder des facades temporaires seulement a l'interieur d'un slice.
4. A la fin, root doit contenir uniquement __init__.py, api.py, main.py.
```

## Architecture Cible

Contrats Pydantic :

```text
decision/message_models.py
  MessageRole
  Message
  Extraction
  MessageReply

domain/planning/view_models.py
  DayId
  ChangeNote
  WatchItem
  DayPlan
  WeeklyPlan
  ScheduledSession
  WorkoutContentView

domain/athlete/view_models.py
  Profile

domain/execution/view_models.py
  Activity

domain/memory/view_models.py
  UserFact
  UserPattern

app/api/read_models.py
  RuntimeDay
  RuntimeWeek
  TodayFitness
  RecentSportActivity
  TodayView

app/api/payloads.py
  MoveSessionPayload

app/api/onboarding_models.py
  OnboardPreview
  OnboardResult
```

ORM SQLAlchemy :

```text
core/orm/
  __init__.py        imports and reexports all ORM classes
  user.py            User, UserConstraint, UserPreference, UserSport
  memory.py          UserFact, WorkingMemoryEntry, UserPattern, MemoryMutationEventRecord
  execution.py       Activity
  integrations.py    StravaConnection
  planning.py        WeeklyPlan, ScheduledSession, DayPlan, ChangeNote, WatchItem,
                     PlanMutationEventRecord, PlanningDecisionRecord
  coaching.py        CoachMessage, ConversationTurnRecord,
                     PendingMutationConfirmation, AdaptationEventRecord
  athlete.py         FitnessSnapshotRecord, ReadinessSnapshotRecord
```

Important :

```text
ORM != domaine pur.
Les classes SQLAlchemy restent infrastructure dans core/orm.
Les repositories domain/* peuvent importer core.orm.
Les modules metier purs ne doivent pas commencer a muter la DB directement.
```

## Invariants

```text
1. Pas de nouvelle logique metier.
2. Pas de changement de table name.
3. Pas de migration DB fonctionnelle dans ce bloc.
4. Pas de write DB hors repositories / services existants.
5. Pas d'import root fitmas.models a la fin.
6. Pas d'import root fitmas.schema a la fin.
7. core/db.py importe core.orm pour enregistrer toutes les tables.
8. Base.metadata.tables contient les memes tables avant/apres.
9. Les response_model FastAPI restent stables.
10. Full backend + smoke core obligatoires avant chaque commit destructif.
```

## Slice 13A — Census Et Tests Anti-Retour

Objectif : poser les gates avant de bouger le code.

Fichiers :

```text
tests/test_phase13a_models_schema_census_architecture.py
```

Tests :

```text
- root models.py est supprime apres 13C
- liste exacte des classes Pydantic par owner
- liste exacte des classes ORM attendues
- liste exacte des table names attendus
```

Verification :

```bash
./scripts/test-backend tests/test_phase13a_models_schema_census_architecture.py -q
```

Commit :

```bash
git commit -m "Add schema models split census"
```

## Slice 13B — Split Pydantic Avec Facade Temporaire

Objectif : sortir le contenu de `models.py` vers les owners, sans changer les
imports appelants.

Creer :

```text
backend/src/fitmas/decision/message_models.py
backend/src/fitmas/domain/planning/view_models.py
backend/src/fitmas/domain/athlete/view_models.py
backend/src/fitmas/domain/execution/view_models.py
backend/src/fitmas/domain/memory/view_models.py
backend/src/fitmas/app/api/onboarding_models.py
```

Modifier :

```text
backend/src/fitmas/app/api/read_models.py
backend/src/fitmas/app/api/payloads.py
backend/src/fitmas/models.py
```

Regle :

```text
models.py devient facade reexport uniquement.
Il ne contient plus aucune classe Pydantic declaree localement.
```

Tests :

```text
- chaque owner expose ses classes
- models.py ne contient pas de class
- les anciens imports via fitmas.models marchent encore temporairement
```

Verification :

```bash
python3 -m compileall -q backend/src/fitmas
./scripts/test-backend tests/test_phase13b_models_facade_architecture.py -q
./scripts/test-backend
```

Commit :

```bash
git commit -m "Split Pydantic contracts by owner"
```

## Slice 13C — Migrer Les Imports Pydantic Puis Supprimer models.py

Objectif : supprimer `backend/src/fitmas/models.py`.

Migration :

```text
fitmas.models.MessageReply        -> fitmas.decision.message_models.MessageReply
fitmas.models.Extraction          -> fitmas.decision.message_models.Extraction
fitmas.models.Message             -> fitmas.decision.message_models.Message
fitmas.models.MessageRole         -> fitmas.decision.message_models.MessageRole
fitmas.models.DayId               -> fitmas.domain.planning.view_models.DayId
fitmas.models.ScheduledSession    -> fitmas.domain.planning.view_models.ScheduledSession
fitmas.models.WeeklyPlan          -> fitmas.domain.planning.view_models.WeeklyPlan
fitmas.models.DayPlan             -> fitmas.domain.planning.view_models.DayPlan
fitmas.models.Profile             -> fitmas.domain.athlete.view_models.Profile
fitmas.models.Activity            -> fitmas.domain.execution.view_models.Activity
fitmas.models.UserFact            -> fitmas.domain.memory.view_models.UserFact
fitmas.models.UserPattern         -> fitmas.domain.memory.view_models.UserPattern
fitmas.models.TodayView           -> fitmas.app.api.read_models.TodayView
fitmas.models.TodayFitness        -> fitmas.app.api.read_models.TodayFitness
fitmas.models.RecentSportActivity -> fitmas.app.api.read_models.RecentSportActivity
fitmas.models.MoveSessionPayload  -> fitmas.app.api.payloads.MoveSessionPayload
fitmas.models.OnboardPreview      -> fitmas.app.api.onboarding_models.OnboardPreview
fitmas.models.OnboardResult       -> fitmas.app.api.onboarding_models.OnboardResult
```

Tests :

```text
- aucun import fitmas.models dans backend/src/fitmas, tests, scripts
- models.py n'existe plus
```

Verification :

```bash
python3 -m compileall -q backend/src/fitmas scripts tests
./scripts/test-backend
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-models-delete-census.json \
  --timeout 420
./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-models-delete-census.json \
  --json-out /tmp/fitmas-models-delete-summary.json
```

Commit :

```bash
git commit -m "Delete root Pydantic models"
```

## Slice 13D — Split ORM Avec Facade Temporaire

Objectif : deplacer les classes SQLAlchemy dans `core/orm`, sans migrer les
call sites tout de suite.

Creer :

```text
backend/src/fitmas/core/orm/__init__.py
backend/src/fitmas/core/orm/user.py
backend/src/fitmas/core/orm/memory.py
backend/src/fitmas/core/orm/execution.py
backend/src/fitmas/core/orm/integrations.py
backend/src/fitmas/core/orm/planning.py
backend/src/fitmas/core/orm/coaching.py
backend/src/fitmas/core/orm/athlete.py
```

Modifier :

```text
backend/src/fitmas/core/db.py
backend/src/fitmas/schema.py
```

Regles techniques :

```text
- relationships en string refs quand elles traversent un fichier.
- TYPE_CHECKING seulement pour les hints si necessaire.
- core/orm/__init__.py importe tous les modules pour enregistrer Base.metadata.
- core/db.py remplace `from fitmas import schema` par `from fitmas.core import orm`.
- schema.py devient facade reexport uniquement.
```

Tests :

```text
- Base.metadata.tables contient exactement les table names attendus
- init_db() cree toutes les tables
- schema.py ne contient pas de class
- imports compat `from fitmas import schema as s` marchent encore temporairement
```

Verification :

```bash
python3 -m compileall -q backend/src/fitmas
./scripts/test-backend tests/test_phase13d_orm_facade_architecture.py -q
./scripts/test-backend
```

Commit :

```bash
git commit -m "Split ORM schema by storage owner"
```

## Slice 13E — Migrer Les Imports ORM

Objectif : couper tous les imports vers `fitmas.schema`.

Migration standard :

```text
from fitmas import schema as s
import fitmas.schema as s
```

devient :

```text
from fitmas.core import orm as s
```

Pourquoi garder `s` temporairement :

```text
Le changement devient un changement de frontiere, pas un refactor de style.
On evite 68 fichiers bruites juste pour renommer l'alias.
```

Tests :

```text
- aucun import fitmas.schema dans backend/src/fitmas, tests, scripts
- core/db.py importe core.orm
```

Verification :

```bash
python3 -m compileall -q backend/src/fitmas scripts tests
./scripts/test-backend
```

Commit :

```bash
git commit -m "Cut imports from root ORM schema"
```

## Slice 13F — Supprimer schema.py

Objectif : supprimer `backend/src/fitmas/schema.py`.

Tests :

```text
- schema.py n'existe plus
- root files = 3
- root contient seulement __init__.py, api.py, main.py
- Base.metadata.tables stable
```

Verification :

```bash
python3 -m compileall -q backend/src/fitmas scripts tests
./scripts/test-backend
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-schema-delete-census.json \
  --timeout 420
./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-schema-delete-census.json \
  --json-out /tmp/fitmas-schema-delete-summary.json
```

Commit :

```bash
git commit -m "Delete root ORM schema"
```

## Slice 13G — Docs Et Root Census Final

Objectif : rendre la nouvelle verite durable.

Modifier :

```text
docs/ARCHITECTURE.md
docs/BUILD-ORDER.md
docs/ROOT-MODULE-CENSUS.md
docs/SYSTEM-MAP.md
```

Etat final attendu :

```text
backend/src/fitmas/
  __init__.py
  api.py
  main.py
```

Verification finale :

```bash
./scripts/docs:list
python3 -m compileall -q backend/src/fitmas scripts tests
./scripts/test-backend
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-root-final-census.json \
  --timeout 420
./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-root-final-census.json \
  --json-out /tmp/fitmas-root-final-summary.json
```

Commit :

```bash
git commit -m "Document root schema cleanup"
```

## Stop Conditions

Stopper le chantier si :

```text
- un test cree une table manquante ou en trop ;
- SQLAlchemy leve une erreur de relationship ou mapper configuration ;
- un endpoint FastAPI change de schema de reponse ;
- le smoke core sort un fallback scenario_count > 0 ;
- une migration commence a melanger ORM split et changement metier ;
- un owner domain pur commence a write directement par accident.
```

## Definition Of Done

```text
- backend/src/fitmas root = __init__.py, api.py, main.py
- aucun import fitmas.models
- aucun import fitmas.schema
- aucun fichier root ajoute
- docs a jour
- backend complet vert
- smoke core vert avec fallback_count=0
```
