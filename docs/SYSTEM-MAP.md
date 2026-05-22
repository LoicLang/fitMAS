---
summary: carte actuelle du systeme FitMAS et des frontieres runtime
read_when:
  - comprendre comment fonctionne FitMAS
  - ajouter une capacite metier
  - modifier une mutation planning
  - expliquer l'architecture a un nouvel agent
---

# System Map

## Boucle Produit

```text
Telegram / App / Scheduler / Ops
-> InputEvent
-> contexte coach
-> understanding LLM
-> decision/domain services
-> command services / mutation service
-> DecisionOutcome
-> reply composer/backend
-> output verifier
-> delivery
```

## Frontieres

### Interfaces

Owners :

- `app/api/`
- `app/telegram/`
- root `api.py` et `main.py` tant que l'assemblage app reste root.

Role :

- recevoir une requete ;
- appeler le runtime/orchestrateur ;
- livrer une reponse ;
- ne pas decider la logique metier.

### Conversation

Etat actuel :

- `decision/conversation_pipeline.py` est un adapter mince.
- La responsabilite conversationnelle restante vit dans les owners
  `decision/turn_*`.
- Les routes close/pending vivent dans `turn_close_route.py` et
  `turn_pending_route.py`; le routeur ne porte plus ces branches en direct.
- `decision/turn_context.py` ne porte plus les helpers prompt/pending ni les
  helpers grounding/payload : ils vivent dans `turn_prompt_context.py` et
  `turn_context_payload.py`.
- Il n'y a plus de bridge `legacy/conversation_*` runtime-active.
- Les replies PlanPatch conversationnelles vivent dans
  `decision/plan_patch_reply.py`.

Interdit :

- ajouter une nouvelle branche opportuniste ;
- parser le texte user libre deterministiquement ;
- faire une reply finale depuis un helper local.

### Decision

Owner :

- `decision/`

Contenu :

- `InputEvent`
- `CoachContext`
- `CoachUnderstanding`
- `DecisionOutcome`
- `CommandBus`
- `DecisionReplyComposer`
- `OutputVerifier`

Regle :

- pas d'import DB lourd ;
- pas d'import `legacy/` ;
- pas de provider LLM direct ;
- pas de write.

### Planning

Owner :

- `domain/planning/`
- `domain/planning/repository.py` pour les reads/writes runtime
  `ScheduledSession`, l'audit `PlanMutationEvent` et les decisions planning.

Pipeline :

```text
RequestedPlanChange
-> ReferenceResolver
-> PlanCandidateBuilder
-> PlanCandidateEvaluator
-> SportPolicy
-> PlanningCommandService / mutation service
```

Verite runtime :

- `ScheduledSession`

Compat seulement :

- `WeeklyPlan`
- `DayPlan`

Owner compat :

- `domain/planning/template_repository.py`
- utilise uniquement pour onboarding, templates et archive historique ;
- ne doit pas redevenir une source runtime conversation/app/heartbeat.

### Execution

Owner :

- `domain/execution/`
- `domain/execution/repository.py` pour `Activity`.

Role :

- lire les activites reelles ;
- enregistrer une activite manuelle ou importee ;
- exposer la conversion API `Activity` ;
- ne pas porter la planification ni les credentials d'integration.

### Athlete

Owner :

- `domain/athlete/`
- `domain/athlete/repository.py` pour user/profile, sports/constraints/
  preferences et snapshots fitness/readiness.

Role :

- convertir et persister l'etat athlete calcule ;
- alimenter app, conversation et heartbeat avec une source unique ;
- ne pas porter planning, execution ni integration.

### Memory

Owner :

- `domain/memory/`
- `domain/memory/repository.py` pour `UserFact`, `WorkingMemoryEntry` et
  `UserPattern`.

Role :

- stocker facts profile ;
- stocker signaux courts en working memory ;
- maintenir patterns observes ;
- ne pas comprendre le texte utilisateur libre.

### Coaching

Owner :

- `domain/coaching/`
- `domain/coaching/repository.py` pour les adaptation events.

Role :

- convertir et persister les decisions d'adaptation visibles ;
- alimenter coach state, app et ops ;
- ne pas porter la mutation planning elle-meme.

### LLM

Owner :

- `llm/`

Contenu :

- gateway provider ;
- prompts ;
- Understanding service ;
- support legacy restant limite a onboarding/fact memory/summaries et reply ;
- provider, parser, tool-loop et artifacts `CoachDecision` supprimes ;
- reply backends LLM.

Regle :

- le LLM comprend et formule ;
- il ne commit pas ;
- il ne porte pas la verite DB.

### Integrations

Owner :

- `integrations/`
- `integrations/repository.py` pour les credentials et metadata Strava.

Role :

- garder le client HTTP dans `integrations/strava.py` ;
- garder la persistence connection/tokens/sync dans `integrations/repository.py` ;
- ne pas exposer ces writes via une facade root.

### Heartbeat

Owner :

- `skills/heartbeat/`

Etat actuel :

- `runtime_adapter.py` convertit heartbeat draft en event/outcome.
- `reply_composer.py` porte la reply proactive.
- le code historique heartbeat reste a simplifier plus tard.

### Legacy

Owner temporaire :

- `legacy/`

Etat actuel :

- aucun module source actif.
- gros residu de compat sorti de `legacy/` :
  `domain/planning/mutation_decision.py`, encore utilise par le writer
  planning historique.
- writer PlanPatch :
  `domain/planning/patch_mutation_service.py`.
- executors planning bas niveau :
  `domain/planning/mutation_executor.py`, `mutation_hooks.py`,
  `mutation_permissions.py`.

Regle :

- aucun nouveau module legacy ;
- tout fichier legacy doit avoir une sortie ;
- si une route legacy n'est plus appelee par runtime reel, elle doit etre supprimee.

## Verifications

Backend complet :

```bash
./scripts/test-backend
```

Smoke core :

```bash
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-core-census.json \
  --timeout 420
```

Docs actives :

```bash
./scripts/docs:list
```
