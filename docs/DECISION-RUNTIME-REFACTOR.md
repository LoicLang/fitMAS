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

- `decision/conversation_pipeline.py` est maintenant un adapter de 78 lignes.
  Il garde l'entree API historique, puis delegue aux owners `decision/turn_*`.
  Le root `conversation_pipeline.py` est supprime.
- La responsabilite conversationnelle restante est concentree dans
  `decision/turn_router.py`, `decision/turn_planning_route.py` et
  `decision/turn_context.py`, pas dans le root pipeline.
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
  plan lookup composee ne cite aucune verite planning, et fallback sur
  l'event execution applique si une reply execution composee est invalide.
- `llm/reply_backend.py` porte les primitives communes de composition/verif
  LLM et re-exporte les owners plus specialises.
- `llm/reply_conversation.py` porte les lanes conversationnelles read-only,
  no-change et execution report.
- `llm/reply_close_turn.py` porte la lane terminal social close.
- `llm/reply_plan_adaptation.py` porte la reply planning-specific
  `AdaptationPolicyDecision -> FinalReplyContext -> verifier`.
- `llm/reply_decision_backend.py` implemente le backend concret du `DecisionReplyComposer`.
- `skills/heartbeat/reply_composer.py` porte la reply heartbeat.

Prochaine simplification :

- pousser plus de verification commune dans `OutputVerifier`.
- garder les replies planning-specific hors du backend generaliste.
- garder `decision/turn_router.py` mince ; ne pas y remettre de logique de decision.
- continuer le menage des prompts conversationnels anciens encore centres sur
  les artefacts PlanPatch historiques.

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

Les sept wrappers legacy P0 ont ete supprimes. Le gros risque suivant etait
`conversation_pipeline.py`; il est desormais un adapter mince. La route planning
canonique a ete sortie vers `decision/turn_planning_route.py`.
`decision/turn_context.py` est passe de `392` a `276` lignes apres extraction
de `turn_prompt_context.py` et `turn_context_payload.py`.
`decision/turn_router.py` est passe de `361` a `172` lignes apres extraction
de `turn_close_route.py`, `turn_pending_route.py` et
`turn_pre_understanding_reply_route.py`, puis du post-understanding vers
`turn_understanding_route.py`. `llm/reply_backend.py` est passe de `367` a
`206` lignes apres extraction de `llm/reply_plan_adaptation.py` et
`llm/reply_close_turn.py`, puis a `75` lignes apres extraction de
`llm/reply_conversation.py`. Les nouveaux hotspots sont
`decision/turn_understanding_route.py`, `decision/turn_planning_route.py` et
les replies LLM specialisees restantes.

10F a ajoute le census conversationnel et supprime quatre bridges :

- `legacy/conversation_activity_highlight_bridge.py`
- `legacy/conversation_canonical_clarification_bridge.py`
- `legacy/conversation_coach_decision_reply_bridge.py`
- `legacy/conversation_decision_bridge.py`

10G a sorti les writes command de `legacy/conversation_*` :

- `decision/command_actions.py`
- `decision/command_mapping.py`
- `decision/command_application.py`
- `decision/command_reply.py` pour la reply post-commandes understanding.

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

10N a sorti le reste du pipeline conversationnel dans des owners explicites :

- `decision/turn_idempotency.py`
- `decision/turn_state.py`
- `decision/turn_calibration.py`
- `decision/turn_context.py`
- `decision/turn_planning_route.py`
- `decision/turn_router.py`
- `decision/turn_finalization.py`
- `decision/turn_persistence.py`
- `decision/turn_recording.py`

`conversation_pipeline.py` n'est plus le hotspot principal. Il ne doit pas
regrossir. `decision/turn_router.py` a ete reduit de `444` a `361` lignes par
extraction de la route planning canonique.

Objectif suivant :

1. reduire `decision/turn_understanding_route.py` si une responsabilite
   nouvelle apparait ;
2. continuer a reduire les replies LLM restantes en owners explicites, puis
   pousser les checks communs vers `OutputVerifier` ;
3. continuer le menage des prompts conversationnels anciens encore centres
   sur les artefacts PlanPatch historiques ;
4. garder les smokes reels comme arbitre de fiabilite, meme quand le provider
   rend les tours lents.

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
