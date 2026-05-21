---
summary: architecture canonique courte du FitMAS Decision Runtime
read_when:
  - modifier conversation_pipeline.py
  - modifier planning, pending, heartbeat, reply ou command services
  - verifier qu'un changement reduit vraiment le runtime
---

# Decision Runtime Refactor

## Objectif

FitMAS doit devenir un runtime de decision sportif :

```text
InputEvent
-> CoachContext
-> Understanding
-> DecisionEngine / domain services
-> CommandBus
-> DecisionOutcome
-> ReplyComposer
-> OutputVerifier
-> Delivery
```

Le refactor n'est pas un rangement de fichiers.
Il retire le pouvoir de decision aux mauvais endroits.

## Doctrine

- LLM-first pour comprendre le langage utilisateur.
- Determinism-first pour verite, validation, permissions, policy, writes et audit.
- Le LLM ne commit jamais.
- Le LLM Understanding ne produit pas de reply finale.
- `ScheduledSession` est la seule verite planning runtime visible.
- `WeeklyPlan` / `DayPlan` restent template, archive ou onboarding.
- Aucun write DB hors services de commande / mutation.
- Aucune reply visible hors reply layer.
- Aucun nouveau parser regex/keyword sur texte utilisateur libre.

## Organisation Cible

```text
backend/src/fitmas/
  app/
    api/
    telegram/
  core/
  domain/
    planning/
    execution/
    memory/
    athlete/
    coaching/
  decision/
  llm/
    prompts/
  integrations/
  legacy/
```

`legacy/` est temporaire.
Il ne doit pas devenir une seconde architecture stable.

## Etat Actuel

En place :

- `decision/` existe comme package pur pour types, outcomes, composer, verifier et command bus.
- `domain/planning/` contient le pipeline canonique `RequestedPlanChange -> candidates -> evaluator -> policy -> command`.
- `llm/` contient gateway, prompts et backends LLM.
- `skills/heartbeat/` contient heartbeat runtime/reply/tool loop.
- `app/api/` et `app/telegram/` commencent a recevoir les entrypoints.

Encore actif :

- `conversation_pipeline.py` reste l'orchestrateur principal, mais il a ete
  reduit de `1819` a `1248` lignes.
- aucun bridge `legacy/conversation_*` mesure ne reste runtime-active.
- le provider, les artifacts et les adapters `CoachDecision` sont supprimes.
- `legacy/` ne contient plus de module source actif.
- `MutationDecision` vit temporairement dans `domain/planning/mutation_decision.py`
  cote planning historique.
- Le writer PlanPatch vit dans `domain/planning/patch_mutation_service.py` ;
  `plan_mutation_service.py` racine est supprime.
- Les executors planning bas niveau vivent dans
  `domain/planning/mutation_executor.py`, `mutation_hooks.py` et
  `mutation_permissions.py`.

## Frontieres

| Couche | Comprend | Decide | Write | Parle |
| --- | ---: | ---: | ---: | ---: |
| Understanding LLM | oui | non | non | non |
| ContextBuilder | non | non | non | non |
| Planning domain | non | oui via policy | non sauf command service | non |
| Command services | non | non | oui | non |
| ReplyComposer / reply backend | non | non | non | oui |
| OutputVerifier | non | non | non | valide seulement |
| Telegram/App/API | non | non | non | delivery |

Si un fichier fait deux roles forts, il est suspect.

## Runtime Planning Cible

```text
RequestedPlanChange
-> ReferenceResolver
-> PlanCandidateBuilder
-> PlanCandidateEvaluator
-> SportPolicy
-> PlanningCommandService
-> PlanMutationEvent / pending / block
-> DecisionOutcome
```

Interdits :

- `PlanPatch` final directement produit par Understanding.
- mutation planning hors `PlanningCommandService` / writer valide.
- fallback planning legacy quand une lane est couverte par le canonique.
- pending duplicate pour la meme intention.

## Reply Cible

```text
DecisionOutcome
-> ReplyRequest
-> DecisionReplyComposer
-> LLMReplyBackend ou fallback machine
-> DecisionOutputVerifier
```

Etat actuel :

- root `final_reply.py` est supprime.
- `decision/plan_patch_reply.py` porte les replies conversationnelles liees aux
  anciens artefacts PlanPatch.
- `decision/readonly_reply.py` fallback sur les facts `PlanWindow` si une reply
  plan lookup composee ne cite aucune verite planning.
- `llm/reply_backend.py` porte les primitives de composition/verif LLM.
- `llm/reply_decision_backend.py` implemente le backend concret du `DecisionReplyComposer`.
- `skills/heartbeat/reply_composer.py` porte la reply heartbeat.

Prochaine simplification :

- reduire `llm/reply_backend.py` et pousser plus de verification dans `OutputVerifier`.
- continuer a reduire `conversation_pipeline.py` autour de turn state,
  idempotence et recording.

## Heartbeat Cible

Heartbeat est une source d'event, pas un systeme parallele.

Etat actuel :

- `skills/heartbeat/runtime_adapter.py` convertit draft heartbeat en `InputEvent + DecisionOutcome`.
- root wrappers heartbeat et adapters legacy ont ete supprimes.
- le code historique heartbeat reste sous `skills/heartbeat/` et doit etre shrinke plus tard.

## Prochain Gros Risque

Planning/pending P0 a ete extrait en 10E :

- `decision/planning_runtime.py`
- `decision/planning_outcomes.py`
- `decision/pending_resolution.py`
- `decision/pending_reply.py`

Les sept wrappers legacy P0 ont ete supprimes. Le prochain gros risque est
desormais la responsabilite restante de `conversation_pipeline.py` : chargement
de turn state, idempotence, orchestration et recording.

10F a ajoute le census conversationnel et supprime quatre bridges :

- `legacy/conversation_activity_highlight_bridge.py`
- `legacy/conversation_canonical_clarification_bridge.py`
- `legacy/conversation_coach_decision_reply_bridge.py`
- `legacy/conversation_decision_bridge.py`

10G a sorti les writes command de `legacy/conversation_*` :

- `decision/command_actions.py`
- `decision/command_mapping.py`
- `decision/command_application.py`

Et supprime :

- `legacy/conversation_command_bridge.py`
- `legacy/conversation_command_bus.py`

10H a sorti readonly/reply de `legacy/conversation_*` :

- `decision/readonly_reply.py`

Et supprime :

- `legacy/conversation_canonical_readonly_bridge.py`
- `legacy/conversation_readonly_reply_bridge.py`

10I a sorti l'understanding runtime de `legacy/conversation_*` :

- `decision/understanding_runtime.py`

Et supprime :

- `legacy/conversation_understanding_bridge.py`

10J a sorti le runtime provider CoachDecision de `legacy/conversation_*` :

- `decision/coach_decision_runtime.py`

Et supprime :

- `legacy/conversation_decide_bridge.py`

10K a supprime le provider CoachDecision callable :

- plus de `ConversationPipelineDependencies.decide`;
- plus de `legacy/coach_decision_provider.py`;
- plus de `build_legacy_coach_decision_request`;
- plus de `run_legacy_coach_decision`;
- les tests core flow qui simulaient le LLM via `api_messages.decide` ont ete
  retires, parce qu'ils protegeaient l'ancien provider au lieu du runtime
  canonique.

Le census courant annonce :

```text
runtime_active_count=0
legacy_internal_count=0
deleted_count=10
```

10L / 10M ont supprime :

- la creation d'artifact compat depuis `CoachUnderstanding` ;
- `legacy/coach_command_adapter.py` ;
- `legacy/coach_decision_artifact.py` ;
- `legacy/coach_understanding_adapter.py` ;
- `legacy/understanding_shadow.py` ;
- `llm/decision_legacy.py` ;
- `llm/legacy_{parser,prompt,action_compile,provider,schema_repair,tool_loop}.py`.

Objectif suivant :

1. ramener `conversation_pipeline.py` vers un adapter plus mince ;
2. continuer le menage des prompts conversationnels anciens encore centres
   sur `CoachDecision`.

## Critere De Verdict

Le refactor marche si, face a un bug, on sait dire :

- bug de contexte ;
- bug d'understanding ;
- bug de candidate planning ;
- bug de policy ;
- bug de command write ;
- bug de reply.

Il echoue si la reponse reste :

- ajouter une regle prompt ;
- ajouter un guard local ;
- ajouter un fallback ;
- ajouter une branche dans `conversation_pipeline.py`.
