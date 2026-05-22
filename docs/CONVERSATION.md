---
summary: contrat actuel du runtime conversationnel et du grounding coach
read_when:
  - modifier conversation_pipeline.py
  - modifier app/api/routes_messages.py
  - toucher aux pending confirmations
  - corriger une hallucination de planning ou d'execution
  - ajouter une action memoire, execution ou planning
---

# Conversation

## But

Le coach Telegram doit repondre depuis la verite runtime, pas depuis un souvenir
de prompt.

Le sujet n'est pas d'injecter plus de contexte.
Le sujet est de construire un `CoachContext` compact, puis de faire passer toute
decision par des artefacts structures.

## Hierarchie De Verite

Ordre strict :

1. `Activity` et evidence execution.
2. Events commits : planning, execution, memory.
3. `ScheduledSession` pour le plan visible.
4. Memoire active avec TTL/statut.
5. Transcript conversationnel recent.
6. `WeeklyPlan` / `DayPlan` seulement template/archive/compat.

Le coach ne doit jamais presenter une seance `adapted` comme faite.
`adapted` signifie modifiee, pas executee.

## Flux Canonique

```text
message Telegram / app
-> InputEvent
-> CoachContext
-> Understanding LLM
-> DecisionRuntime / bridges restants
-> CommandBus / mutation services
-> DecisionOutcome
-> ReplyComposer
-> OutputVerifier
-> delivery
```

Etat actuel :

- `decision/conversation_pipeline.py` est devenu un adapter mince de 78 lignes :
  user, idempotence, calibration, contexte, puis delegation au router. Le root
  `conversation_pipeline.py` est supprime.
- `decision/` porte deja les types et l'outcome canonique.
- `llm/understanding_service.py` porte l'understanding cible.
- `decision/understanding_runtime.py` porte l'appel understanding canonique.
- `decision/turn_state.py`, `decision/turn_context.py`,
  `decision/turn_calibration.py`, `decision/turn_planner.py`,
  `decision/turn_router.py`,
  `decision/turn_planning_route.py`, `decision/turn_finalization.py`,
  `decision/turn_persistence.py` et `decision/turn_idempotency.py` portent
  les anciens blocs du pipeline.
- `decision/plan_patch_reply.py` porte les helpers de reply PlanPatch qui
  vivaient auparavant dans le pipeline.
- `decision/readonly_reply.py` refuse une reply plan lookup non grounded quand
  des facts `PlanWindow` permettent un fallback factuel ; pour une execution
  appliquee, le fallback visible parle depuis l'event machine.
- `decision/command_reply.py` porte la reply visible apres commandes
  understanding memoire/execution appliquees ou bloquees.
- `decision/grounding.py` porte les facts compactes de grounding visibles par
  les reply composers et verifiers.
- `decision/coach_decision_runtime.py` ne porte plus le provider compat :
  il trace `coach_decision_provider_removed` et compose une clarification
  canonique si aucune lane canonique ne sait traiter.
- aucun bridge `legacy/conversation_*` ne reste runtime-active.
- planning, pending, command writes, activity highlight, clarification,
  readonly/reply et understanding ne vivent plus dans ces petits wrappers
  legacy.
- `CoachDecision` n'existe plus comme provider, artifact ou adapter runtime.

## Regles Dures

- Aucun regex/keyword sur texte utilisateur libre.
- Aucun parsing local de `oui`, `non`, fatigue, douleur, sport, date, execution.
- Le LLM comprend, le backend valide.
- Les tools LLM sont read-only ou validation-only.
- Les writes passent apres validation par service officiel.
- Une reply visible doit venir d'un outcome/verdict, pas d'un helper local.
- Un claim d'action sans event committe doit etre bloque ou repare.

## Artefacts Conversationnels

Transition actuelle :

- `CoachUnderstanding` separe comprehension et decision.
- Les commandes memoire/execution viennent directement de l'understanding ou du
  turn plan structure, pas d'un artifact `CoachDecision`.
- `DecisionOutcome` est la cible pour parler au user.

Actions structurees encore acceptees :

- `memory_actions[]`
- `execution_actions[]`
- `plan_patch` / `requires_confirmation` en migration
- `pending_resolution`

Le backend ne lit pas ces actions comme du texte humain.
Il les resout contre DB, schemas, IDs, dates, permissions et policies.

Interdit depuis 10M :

```text
api_messages.decide
ConversationPipelineDependencies.decide
legacy/coach_decision_provider.py
run_legacy_coach_decision
llm/decision_legacy.py
legacy/coach_decision_artifact.py
```

## Pending

Une confirmation courte est comprise par le LLM dans son contexte.

Interdit :

```text
if user_text.lower() in {"oui", "ok", "non"}:
```

Autorise :

```text
pending_resolution
-> verifier pending active unique/non expiree
-> revalider artefact stocke
-> commit / reject / clarify / keep open
```

Le pending runtime vit maintenant dans `decision/pending_resolution.py`.
Le pipeline conversation ne porte plus lui-meme les branches pending ; elles
vivent dans le router et les services de decision.

## Planning

La cible planning est :

```text
RequestedPlanChange
-> ReferenceResolver
-> CandidateBuilder
-> Evaluator
-> Policy
-> PlanningCommandService / mutation service
-> DecisionOutcome
```

Le LLM ne doit pas devenir le writer.
Un `PlanPatch` reste un artefact backend validable, pas une verite finale.

## Reply

Reply actuelle :

- `decision/reply_composer.py`
- `decision/readonly_reply.py`
- `decision/plan_patch_reply.py`
- `llm/reply_backend.py`
- `llm/reply_conversation.py`
- `llm/reply_close_turn.py`
- `llm/reply_plan_adaptation.py`
- `llm/reply_decision_backend.py`
- `decision/output_verifier.py`
- `skills/heartbeat/reply_composer.py`

Root `final_reply.py` n'existe plus.
Ne pas le recreer.

## Idempotence Telegram

Chaque message Telegram transmis a l'API porte une cle stable :

- message seul : `telegram:{chat_id}:{message_id}`
- batch debounce : `telegram:{chat_id}:{first_message_id}-{last_message_id}`

Si la meme cle revient, le backend doit renvoyer le tour persiste au lieu de
rejouer LLM/mutation.

## Scenarios A Proteger

- `redonne le plan actuel`
- `echange mardi et mercredi`
- `je ne peux pas nager deux semaines`
- `j'ai mal au genou`
- `j'ai fait la seance hier`
- `pas eu le temps`
- `oui`
- `non finalement vendredi`

Pour chaque scenario, verifier :

- intent / understanding ;
- outcome ;
- events appliques ou absence d'event ;
- pending cree/ferme ;
- reply sans claim faux.
