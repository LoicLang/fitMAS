---
summary: kill list courte des surfaces legacy restantes du Decision Runtime
read_when:
  - supprimer du legacy
  - choisir le prochain slice de shrink
  - verifier qu'une route legacy ne revient pas
---

# Decision Runtime Legacy Kill List

## Etat Court

Le dossier `legacy/` n'a plus de module source actif. Le bloc P0
planning/pending, la compat `CoachDecision` et `MutationDecision` n'y vivent
plus.

Les wrappers deja supprimes :

- `legacy/conversation_reply_adapter.py`
- `legacy/final_reply_backend.py`
- `legacy/heartbeat_runtime_adapter.py`
- `legacy/heartbeat_skill_bridge.py`
- `legacy/tools_compat.py`
- `legacy/weekly_plan_compat.py`
- `legacy/conversation_activity_highlight_bridge.py`
- `legacy/conversation_canonical_clarification_bridge.py`
- `legacy/conversation_coach_decision_reply_bridge.py`
- `legacy/conversation_command_bridge.py`
- `legacy/conversation_command_bus.py`
- `legacy/conversation_decision_bridge.py`
- `legacy/conversation_canonical_readonly_bridge.py`
- `legacy/conversation_readonly_reply_bridge.py`
- `legacy/conversation_understanding_bridge.py`
- `legacy/conversation_decide_bridge.py`
- `legacy/coach_decision_provider.py`
- `legacy/coach_command_adapter.py`
- `legacy/coach_decision_artifact.py`
- `legacy/coach_understanding_adapter.py`
- `legacy/understanding_shadow.py`
- `llm/decision_legacy.py`
- `llm/legacy_parser.py`
- `llm/legacy_prompt.py`
- `llm/legacy_action_compile.py`
- `llm/legacy_provider.py`
- `llm/legacy_schema_repair.py`
- `llm/legacy_tool_loop.py`
- `legacy/decision_contracts.py`

Le gros residu actif n'est plus le dossier `legacy/`.
Le writer PlanPatch vit dans `domain/planning/patch_mutation_service.py`.
Les executors planning bas niveau vivent dans `domain/planning/`.
Les helpers de reply PlanPatch conversationnels vivent dans
`decision/plan_patch_reply.py`.
Le prochain risque est le reste de `conversation_pipeline.py`.

## Priorite De Suppression

### P0 — Planning / Pending — clos en 10E

Fichiers supprimes :

- `legacy/conversation_canonical_planning_bridge.py`
- `legacy/conversation_pending_bridge.py`
- `legacy/conversation_planning_bridge.py`
- `legacy/planning_runtime_adapter.py`
- `legacy/planning_outcome_adapter.py`
- `legacy/plan_patch_reply_adapter.py`
- `legacy/pending_reply_adapter.py`

Nouveaux owners :

- `decision/planning_runtime.py`
- `decision/planning_outcomes.py`
- `decision/pending_resolution.py`
- `decision/pending_reply.py`

Census final :

```text
runtime_active_count=0
legacy_internal_count=0
test_only_count=0
deleted_count=7
```

Etat :

- l'actif planning/pending est sorti de `legacy/`;
- les wrappers vides sont supprimes ;
- le reste du travail est dans `conversation_pipeline.py`, pas dans ces fichiers.

### P1 — CoachDecision / Understanding Legacy — clos en 10M / 10N

Fichiers supprimes :

- `legacy/decision_contracts.py`
- `legacy/coach_decision_artifact.py`
- `legacy/coach_understanding_adapter.py`
- `legacy/understanding_shadow.py`
- `llm/decision_legacy.py`

Probleme :

- `CoachDecision` ne reste plus comme contrat runtime ou provider.
- `decision/understanding_runtime.py` trace directement l'understanding
  canonique sans fabriquer d'artifact compat.

Sortie attendue :

- `legacy/coach_decision_artifact.py`, `legacy/coach_understanding_adapter.py`,
  `legacy/understanding_shadow.py` et `llm/decision_legacy.py` supprimes.
- `legacy/decision_contracts.py` supprime.
- `MutationDecision` vit temporairement dans
  `domain/planning/mutation_decision.py` jusqu'au shrink du writer planning.
- `plan_mutation_service.py` racine est supprime.
- Le writer PlanPatch vit dans `domain/planning/patch_mutation_service.py`.
- `mutations.py`, `mutation_hooks.py`, `mutation_permissions.py` racine
  supprimes.

### P2 — Commands / Memory / Execution Bridges — clos en 10G

Fichiers supprimes :

- `legacy/conversation_command_bridge.py`
- `legacy/conversation_command_bus.py`

Nouveaux owners :

- `decision/command_actions.py`
- `decision/command_mapping.py`
- `decision/command_application.py`

Etat :

- `legacy/coach_command_adapter.py` est supprime ;
- les writes memoire/execution conversationnels passent par
  `decision/command_application.py` ;
- les action contracts ne sont plus definis dans un contrat legacy.

### P3 — Readonly / Activity / Clarification Bridges — clos en 10H

Fichiers supprimes :

- `legacy/conversation_activity_highlight_bridge.py`
- `legacy/conversation_canonical_clarification_bridge.py`
- `legacy/conversation_canonical_readonly_bridge.py`
- `legacy/conversation_coach_decision_reply_bridge.py`
- `legacy/conversation_decision_bridge.py`
- `legacy/conversation_readonly_reply_bridge.py`

Nouveaux owners :

- `decision/activity_highlight.py`
- `decision/clarification_reply.py`
- `decision/readonly_reply.py`

Etat :

- read-only, activity highlight et clarification ne vivent plus dans des
  wrappers `legacy/conversation_*`;
- les helpers de reply `CoachDecision` ont ete retires apres 10M ;
- le dernier risque actif est `conversation_pipeline.py`.

### P4 — Conversation Bridge Census — clos en 10J / 10K / 10M

Commande :

```bash
./scripts/decision-runtime-conversation-bridge-census \
  --json-out /tmp/fitmas-10j-conversation-bridge-census.json
```

Resultat courant apres 10J :

```text
runtime_active_count=0
legacy_internal_count=0
test_only_count=0
deleted_count=10
```

Encore runtime-active :

- aucun bridge `legacy/conversation_*` mesure.
- aucun provider `legacy/coach_decision_provider.py`.
- aucun artifact ou LLM path `CoachDecision`.

## Gates A Garder

- Aucun import de legacy depuis `decision/`.
- Aucun import de deleted wrapper.
- Aucun fallback legacy sur lane couverte par smoke.
- Aucun `PlanPatch` produit par Understanding.
- Aucun `MutationDecision` dans le chemin runtime canonique.
- Aucun texte visible hors reply layer.

## Dernier Cut Conversation

Apres 10P : les helpers de reply PlanPatch sont sortis vers
`decision/plan_patch_reply.py`.

Resultat :

- `conversation_pipeline.py` : `1819` -> `1248` lignes.
- Nouveau gate : le pipeline ne peut plus redefinir les helpers de reply
  PlanPatch.
- Le dossier `legacy/` reste vide de module source actif.

## Prochain Slice

Continuer le shrink de `conversation_pipeline.py` sans recréer de fallback
local : turn state, idempotence, recording.

Commande :

```bash
./scripts/decision-runtime-conversation-bridge-census \
  --json-out /tmp/fitmas-10j-conversation-bridge-census.json
```

Resultat 10J :

- census conversationnel ajoute ;
- activity highlight et clarification vivent dans `decision/`;
- helpers de forme `CoachDecision` supprimes ;
- readonly/reply vit dans `decision/readonly_reply.py`;
- understanding runtime vit dans `decision/understanding_runtime.py`;
- le provider CoachDecision callable est supprime ;
- `decision/coach_decision_runtime.py` ne garde que la trace
  `coach_decision_provider_removed` et la clarification canonique ;
- command mapping/application vit dans `decision/`;
- dix bridges conversationnels sont supprimes ;
- aucun bridge `legacy/conversation_*` ne reste actif.
