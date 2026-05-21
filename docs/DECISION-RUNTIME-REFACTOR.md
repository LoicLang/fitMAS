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

- `conversation_pipeline.py` reste le mega-orchestrateur principal.
- `legacy/conversation_*` contient encore des bridges conversationnels, mais
  planning/pending, commands et readonly/reply sont deja sortis.
- `llm/decision_legacy.py` et `legacy/decision_contracts.py` portent encore le contrat `CoachDecision`.

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
- `llm/reply_backend.py` porte les primitives de composition/verif LLM.
- `llm/reply_decision_backend.py` implemente le backend concret du `DecisionReplyComposer`.
- `skills/heartbeat/reply_composer.py` porte la reply heartbeat.

Prochaine simplification :

- reduire `llm/reply_backend.py` et pousser plus de verification dans `OutputVerifier`.
- reduire `conversation_pipeline.py` maintenant que planning/pending n'est plus
  porte par des bridges legacy.

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
desormais la taille de `conversation_pipeline.py` et les bridges conversationnels
restants.

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

Le census courant annonce :

```text
runtime_active_count=1
legacy_internal_count=0
deleted_count=9
```

Objectif suivant :

1. mesurer les callers reels des bridges restants ;
2. extraire seulement l'actif ;
3. supprimer physiquement les wrappers vides ;
4. ramener `conversation_pipeline.py` vers un adapter plus mince.

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
