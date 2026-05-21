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

- `conversation_pipeline.py` reste le gros orchestrateur.
- Il est en train d'etre reduit vers `DecisionRuntime`.
- Les bridges restants vivent encore sous `legacy/conversation_*`.

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

- `2` modules restants : `__init__.py` et `decision_contracts.py`.
- gros residu : `MutationDecision`, encore utilise par le writer planning
  historique.

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
